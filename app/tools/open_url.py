import asyncio
import aiohttp
import html2text
import re
import lxml.etree
import lxml.html
from urllib.parse import urljoin, urlparse
from pydantic import BaseModel, Field

from app.utils import States


class OpenModel(BaseModel):
    id: str | None = Field(description="The ID of the link to open. Valid link ids are displayed with the formatting: `【{id}†.*】`. If you want to open url directly, pass the url as `id`.", default=None)
    loc: int = Field(description="The line number to start from.", default=-1)
    num_lines: int = Field(description="The number of lines to show.", default=100)


OPEN_URL = {
    "type": "function",
    "function": {
        "name": "open",
        "description": "Opens the link `id` or `url` from the page indicated by `cursor` or starting at line number `loc`, showing `num_lines` lines. Use this function without `id` to scroll to a new location of an opened page.",
        "parameters": OpenModel.model_json_schema()
    }
}


HTML_SUP_RE = re.compile(r"<sup( [^>]*)?>([\w\-]+)</sup>")
HTML_SUB_RE = re.compile(r"<sub( [^>]*)?>([\w\-]+)</sub>")
HTML_TAGS_SEQ_RE = re.compile(r"(?<=\w)((<[^>]*>)+)(?=\w)")
WHITESPACE_ANCHOR_RE = re.compile(r"(【\@[^】]+】)(\s+)")
EMPTY_LINE_RE = re.compile(r"^\s+$", flags=re.MULTILINE)
EXTRA_NEWLINE_RE = re.compile(r"\n(\s*\n)+")


async def open(
    states: States,
    **tool_input
):
    def is_url(url: str) -> bool:
        return url.startswith("http")
    
    def make_response(page_contents: PageContents, loc: int, num_lines: int) -> str:
        lines = page_contents.text.splitlines()
        if not lines:
            return ""
        if loc >= len(lines):
            return f"Invalid location parameter: `{loc}`. Cannot exceed page maximum of {len(lines) - 1}."
        start = 0 if loc < 0 else max(0, min(loc, len(lines)))
        end = min(len(lines), start + num_lines)
        lines_to_show = lines[start:end]
        domain = urlparse(page_contents.url).netloc
        body = "\n".join(lines_to_show)
        header = (
            f"# 【{states.turn}:0†{page_contents.title}†{domain}】\n"
            f"**viewing lines [{start} - {end-1}] of {len(lines)}**"
        )

        return f"{header}\n\n```contents\n{body}\n```"
    
    try:
        tool_input = OpenModel(**tool_input)
    except Exception as e:
        return f"Error validating `open`: {e}"
    
    url: str | None = None
    # 1) URL 직접 열기
    if tool_input.id and is_url(tool_input.id):
        url = tool_input.id
    # 2) 스크롤(현재 페이지에서 loc/num_lines만 변경)
    elif tool_input.id is None:
        curr_url = getattr(states.tool_state, "current_url", None)
        if curr_url and curr_url in states.tool_state.url_to_page:
            page = states.tool_state.url_to_page[curr_url]
            return make_response(page, tool_input.loc, tool_input.num_lines)
        else:
            return "There is no opened page. Please provide a link `id` or a direct URL."
    # 3) 링크 ID 열기
    else:
        link_url = states.tool_state.id_to_url.get(tool_input.id)
        if not link_url:
            return f"Unknown link ID: {tool_input.id}. Please provide a link `id` or a direct URL."
        url = link_url
    
    # 페이지 열고 상태 갱신
    try:
        page_contents = await open_url(url, states.turn)
    except Exception as e:
        return f"Failed to open page: {e}"
    
    states.tool_state.url_to_page[url] = page_contents
    states.tool_state.current_url = url
    states.tool_state.id_to_url[f"{states.turn}:0"] = url
    for link_id, link_target in page_contents.urls.items():
        states.tool_state.id_to_url[f"{states.turn}:{link_id}"] = link_target
    response = make_response(page_contents, tool_input.loc, tool_input.num_lines)
    states.turn += 1
    return response


class PageContents(BaseModel):
    url: str
    text: str
    title: str
    urls: dict[str, str]


async def open_url(
    url: str,
    turn: int
) -> PageContents:
        
    _download_cache = {}
    
    async def download_async(url: str) -> str:
        if url in _download_cache:
            return _download_cache[url]
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36',
            'Referer': 'https://www.google.com/',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8'
        }
        
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                async with session.get(url, headers=headers) as resp:
                    resp.raise_for_status()
                    content = await resp.text()
                    if len(_download_cache) < 128:
                        _download_cache[url] = content
                    return content
        except aiohttp.ClientError as e:
            raise Exception(f"다운로드 실패: {e}")
        except Exception as e:
            raise Exception(f"알 수 없는 오류: {e}")

    def get_domain(url: str) -> str:
        """Extracts the domain from a URL."""
        if "http" not in url:
            # If `get_domain` is called on a domain, add a scheme so that the
            # original domain is returned instead of the empty string.
            url = "http://" + url
        return urlparse(url).netloc

    def multiple_replace(text: str, replacements: dict[str, str]) -> str:
        """Performs multiple string replacements using regex pass."""
        regex = re.compile("(%s)" % "|".join(map(re.escape, replacements.keys())))
        return regex.sub(lambda mo: replacements[mo.group(1)], text)

    def _replace_special_chars(text: str) -> str:
        """Replaces specific special characters with visually similar alternatives."""
        replacements = {
            "【": "〖",
            "】": "〗",
            "◼": "◾",
            # "━": "─",
            "\u200b": "",  # zero width space
            # Note: not replacing †
        }
        return multiple_replace(text, replacements)


    def merge_whitespace(text: str) -> str:
        """Replace newlines with spaces and merge consecutive whitespace into a single space."""
        text = text.replace("\n", " ")
        text = re.sub(r"\s+", " ", text)
        return text


    def arxiv_to_ar5iv(url: str) -> str:
        """Converts an arxiv.org URL to its ar5iv.org equivalent."""
        return re.sub(r"arxiv.org", r"ar5iv.org", url)


    def _clean_links(root: lxml.html.HtmlElement, cur_url: str, turn: int) -> dict[str, str]:
        """Processes all anchor tags in the HTML, replaces them with a custom format and returns an ID-to-URL mapping."""
        cur_domain = get_domain(cur_url)
        urls: dict[str, str] = {}
        urls_rev: dict[str, str] = {}
        for a in root.findall(".//a[@href]"):
            assert a.getparent() is not None
            link = a.attrib["href"]
            if link.startswith(("mailto:", "javascript:")):
                continue
            text = _get_text(a).replace("†", "‡")
            if not re.sub(r"【\@([^】]+)】", "", text):  # Probably an image
                continue
            if link.startswith("#"):
                replace_node_with_text(a, text)
                continue
            try:
                link = urljoin(cur_url, link)  # works with both absolute and relative links
                domain = get_domain(link)
            except Exception:
                domain = ""
            if not domain:
                continue
            link = arxiv_to_ar5iv(link)
            if (link_id := urls_rev.get(link)) is None:
                link_id = f"{len(urls) + 1}"
                urls[link_id] = link
                urls_rev[link] = link_id
            if domain == cur_domain:
                replacement = f"【{turn}:{link_id}†{text}】"
            else:
                replacement = f"【{turn}:{link_id}†{text}†{domain}】"
            replace_node_with_text(a, replacement)
        return urls

    def _get_text(node: lxml.html.HtmlElement) -> str:
        """Extracts all text from an HTML element and merges it into a whitespace-normalized string."""
        return merge_whitespace(" ".join(node.itertext()))

    def _remove_node(node: lxml.html.HtmlElement) -> None:
        """Removes a node from its parent in the lxml tree."""
        node.getparent().remove(node)

    def _escape_md(text: str) -> str:
        return text

    def _escape_md_section(text: str, snob: bool = False) -> str:
        return text

    def html_to_text(html: str) -> str:
        """Converts an HTML string to clean plaintext."""
        html = re.sub(HTML_SUP_RE, r"^{\2}", html)
        html = re.sub(HTML_SUB_RE, r"_{\2}", html)
        # add spaces between tags such as table cells
        html = re.sub(HTML_TAGS_SEQ_RE, r" \1", html)
        # we don't need to escape markdown, so monkey-patch the logic
        orig_escape_md = html2text.utils.escape_md
        orig_escape_md_section = html2text.utils.escape_md_section
        html2text.utils.escape_md = _escape_md
        html2text.utils.escape_md_section = _escape_md_section
        h = html2text.HTML2Text()
        h.ignore_links = True
        h.ignore_images = True
        h.body_width = 0  # no wrapping
        h.ignore_tables = True
        h.unicode_snob = True
        h.ignore_emphasis = True
        result = h.handle(html).strip()
        html2text.utils.escape_md = orig_escape_md
        html2text.utils.escape_md_section = orig_escape_md_section
        return result


    def _remove_math(root: lxml.html.HtmlElement) -> None:
        """Removes all <math> elements from the lxml tree."""
        for node in root.findall(".//math"):
            _remove_node(node)

    def _remove_by_tags(root: lxml.html.HtmlElement, tags: list[str]) -> None:
        """Remove all nodes matching given tag names from the lxml tree."""
        for tag in tags:
            for node in root.findall(f".//{tag}"):
                _remove_node(node)

    def _remove_by_attributes(root: lxml.html.HtmlElement) -> None:
        """Remove nodes that match common non-content attributes (ads, cookie, nav, etc.)."""
        # roles that usually denote non-core content
        roles = [
            "navigation", "banner", "contentinfo", "complementary", "search",
            "dialog", "alert", "alertdialog", "toolbar", "tablist"
        ]
        # tokens that frequently appear in class names for non-content blocks
        class_tokens = [
            "ad", "ads", "advertisement", "banner", "cookie", "consent", "gdpr",
            "popup", "popover", "modal", "subscribe", "newsletter", "paywall",
            "login", "signin", "signup", "share", "social", "breadcrumb",
            "pagination", "pager", "sidebar", "related", "recommend", "toc",
            "comments", "comment"
        ]
        # gather nodes via XPath queries
        nodes_to_remove: set[lxml.html.HtmlElement] = set()
        # roles
        for role in roles:
            for n in root.xpath(f".//*[@role='{role}']"):
                nodes_to_remove.add(n)
        # class tokens (case-insensitive, token-aware)
        for token in class_tokens:
            xpath_expr = (
                "//*[contains(concat(' ', normalize-space(translate(@class, "
                "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')), ' '), "
                f"' {token} ')]"
            )
            for n in root.xpath(xpath_expr):
                nodes_to_remove.add(n)
        # id substring match (case-insensitive)
        for token in class_tokens:
            xpath_expr = (
                "//*[contains(translate(@id, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), "
                f"'{token}')]"
            )
            for n in root.xpath(xpath_expr):
                nodes_to_remove.add(n)
        # remove collected nodes
        for n in list(nodes_to_remove):
            _remove_node(n)


    def remove_unicode_smp(text: str) -> str:
        """Removes Unicode characters in the Supplemental Multilingual Plane (SMP) from `text`.

        SMP characters are not supported by lxml.html processing.
        """
        smp_pattern = re.compile(r"[\U00010000-\U0001FFFF]", re.UNICODE)
        return smp_pattern.sub("", text)

    def replace_node_with_text(node: lxml.html.HtmlElement, text: str) -> None:
        """Replaces an lxml node with a text string while preserving surrounding text."""
        previous = node.getprevious()
        parent = node.getparent()
        tail = node.tail or ""
        if previous is None:
            parent.text = (parent.text or "") + text + tail
        else:
            previous.tail = (previous.tail or "") + text + tail
        parent.remove(node)

    def replace_images(
        root: lxml.html.HtmlElement
    ) -> None:
        """Finds all image tags and replaces them with numbered placeholders (includes alt/title if available)."""
        cnt = 0
        for img_tag in root.findall(".//img"):
            image_name = img_tag.get("alt", img_tag.get("title"))
            if image_name:
                replacement = f"[Image {cnt}: {image_name}]"
            else:
                replacement = f"[Image {cnt}]"
            replace_node_with_text(img_tag, replacement)
            cnt += 1

    def process_html(
        html: str,
        url: str
    ):
        """Convert HTML into model-readable version."""
        html = remove_unicode_smp(html)
        html = _replace_special_chars(html)
        root = lxml.html.fromstring(html)

        # 상단/하단/내비/미디어/양식 등 비콘텐츠성 태그 제거
        _remove_by_tags(root, [
            "header", "footer", "nav", "aside", "form",
            "iframe", "script", "style", "noscript", "template",
            "svg", "canvas", "video", "audio", "source", "track",
            "object", "embed"
        ])
        # 속성 기반(ads/cookie/popup/nav 등) 비콘텐츠 영역 제거
        _remove_by_attributes(root)

        # Parse the title.
        title_element = root.find(".//title")
        if title_element is not None:
            final_title = title_element.text or ""
        elif url and (domain := get_domain(url)):
            final_title = domain
        else:
            final_title = ""

        urls = _clean_links(root, url, turn)
        replace_images(root=root)
        _remove_math(root)
        clean_html = lxml.etree.tostring(root, encoding="UTF-8").decode()
        text = html_to_text(clean_html)
        text = re.sub(WHITESPACE_ANCHOR_RE, lambda m: m.group(2) + m.group(1), text)
        # ^^^ move anchors to the right thru whitespace
        # This way anchors don't create extra whitespace
        text = re.sub(EMPTY_LINE_RE, "", text)
        # ^^^ Get rid of empty lines
        text = re.sub(EXTRA_NEWLINE_RE, "\n\n", text)
        # ^^^ Get rid of extra newlines

        return PageContents(
            url=url,
            text=text,
            urls=urls,
            title=final_title,
        )
    
    html = await download_async(url)
    return process_html(html, url)


if __name__ == "__main__":
    page = asyncio.run(open_url("https://ko.wikipedia.org/wiki/%ED%8C%8C%EC%9D%B4%EC%8D%AC", 0))
    print(page)
