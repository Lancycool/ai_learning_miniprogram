"""Child entry point. Only controlled messages leave this isolated parser."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import re
import sys


class ParseFailure(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


def normalize(text):
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")


def chapter_ranges(text, headings):
    unique = {offset: (title[:160], level) for offset, title, level in headings}
    ordered = sorted(unique.items())
    if not ordered or ordered[0][0] > 0:
        ordered.insert(0, (0, ("未分章内容", 1)))
    chapters = []
    for index, (offset, (title, level)) in enumerate(ordered):
        end = len(text)
        for later_offset, (_, later_level) in ordered[index+1:]:
            if later_level <= level or title == "未分章内容":
                end = later_offset
                break
        if end > offset:
            chapters.append({"title": title, "level": level, "start_offset": offset, "end_offset": end})
    return chapters


def plain_headings(text, markdown=False):
    headings = []
    offset, fenced = 0, False
    for line in text.splitlines(keepends=True):
        if markdown and line.strip().startswith(("```", "~~~")):
            fenced = not fenced
        match = re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$", line) if markdown and not fenced else None
        if match:
            headings.append((offset, match[2], len(match[1])))
        elif not fenced and re.match(r"^\s*第[一二三四五六七八九十百零〇\d]+[章节篇部分]\s*[^\n]{0,100}$", line.rstrip()):
            headings.append((offset, line.strip(), 2 if "节" in line[:20] else 1))
        offset += len(line)
    return headings


def load_document(path, extension, limits):
    from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, UnstructuredMarkdownLoader, TextLoader
    warnings, locations, extra_headings = [], [], []
    if extension == "pdf":
        from pypdf import PdfReader
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise ParseFailure("encrypted_pdf", "系统暂不支持加密 PDF，请解密后上传")
        if len(reader.pages) > limits["pages"]:
            raise ParseFailure("page_limit", "PDF 页数超过处理上限，请拆分后上传")
        def page_has_image(page):
            resources = page.get('/Resources', {})
            resources = resources.get_object() if hasattr(resources, 'get_object') else resources
            objects = resources.get('/XObject', {})
            objects = objects.get_object() if hasattr(objects, 'get_object') else objects
            return any(obj.get_object().get('/Subtype') == '/Image' for obj in objects.values()
                       if hasattr(obj, 'get_object'))
        if any(page_has_image(page) for page in reader.pages):
            warnings.append({'code': 'embedded_images', 'message': 'PDF 包含图片，系统只解析文字；请核对图片依赖内容'})
        documents = PyPDFLoader(path, mode="page", extract_images=False).load()
        parts, offset = [], 0
        for page_no, document in enumerate(documents):
            content = normalize(document.page_content)
            if not content.strip():
                # A page with no selectable text may contain unparsed image questions.
                raise ParseFailure("scanned_pdf", "PDF 含有无法读取的页面，请上传文字版资料；扫描件后续支持")
            parts.append(content)
            locations.append({"start_offset": offset, "end_offset": offset+len(content), "page": page_no+1})
            offset += len(content)+1
        text, loader = "\n".join(parts), "PyPDFLoader"
        def outlines(items):
            for item in items:
                if isinstance(item, list):
                    outlines(item)
                else:
                    title = str(item.get("/Title", ""))
                    position = text.find(title)
                    if title and position >= 0:
                        extra_headings.append((position, title, 1))
        outlines(reader.outline)
    elif extension == "docx":
        from docx import Document
        text = normalize("\n".join(d.page_content for d in Docx2txtLoader(path).load()))
        document, cursor = Document(path), 0
        for paragraph in document.paragraphs:
            style = paragraph.style.name if paragraph.style else ""
            match = re.match(r"(?:Heading|标题)\s*(\d+)", style, re.IGNORECASE)
            if match and paragraph.text.strip():
                position = text.find(paragraph.text, cursor)
                if position >= 0:
                    extra_headings.append((position, paragraph.text, min(6, int(match[1]))))
                    cursor = position+len(paragraph.text)
        if document.inline_shapes:
            warnings.append({"code": "embedded_images", "message": "文档包含图片，系统只解析文字；请核对图片依赖内容"})
        loader = "Docx2txtLoader"
    elif extension in ("md", "markdown"):
        # The selected loader validates the local file. Raw Markdown preserves options,
        # answers, headings and literal offsets that an HTML conversion would erase.
        UnstructuredMarkdownLoader(path, mode="single").load()
        text, loader = normalize(path.read_text(encoding="utf-8-sig")), "UnstructuredMarkdownLoader"
        if re.search(r"!\[|<img\b", text, re.IGNORECASE):
            warnings.append({"code": "embedded_images", "message": "Markdown 包含图片引用，系统只解析文字；请核对图片依赖内容"})
    elif extension == "txt":
        try:
            text = normalize("\n".join(d.page_content for d in TextLoader(path, encoding="utf-8-sig").load()))
        except RuntimeError:
            try:
                text = normalize("\n".join(d.page_content for d in TextLoader(path, encoding="gb18030").load()))
            except RuntimeError:
                raise ParseFailure("unsupported_encoding", "文字编码无法识别，请保存为 UTF-8 后上传") from None
        loader = "TextLoader"
    else:
        raise ParseFailure("unsupported_format", "系统只支持 PDF、DOCX、Markdown 和 TXT")
    if not text.strip():
        raise ParseFailure("empty_text", "系统没有读取到文字，请上传文字版资料")
    if len(text) > limits["characters"]:
        raise ParseFailure("text_limit", "文档文字超过处理上限，请拆分后上传")
    headings = plain_headings(text, extension in ("md", "markdown"))
    headings.extend(extra_headings)
    return {"text": text, "chapters": chapter_ranges(text, headings), "locations": locations,
            "warnings": warnings, "loader": loader}


def main():
    try:
        with redirect_stdout(io.StringIO()):
            value = load_document(Path(sys.argv[1]), sys.argv[2], json.loads(sys.argv[3]))
    except ParseFailure as exc:
        value = {"error": {"code": exc.code, "message": exc.message}}
    except Exception:
        value = {"error": {"code": "invalid_file", "message": "资料内容无法解析，请检查文件后重试"}}
    sys.stdout.write(json.dumps(value, ensure_ascii=False))


if __name__ == "__main__":
    main()
