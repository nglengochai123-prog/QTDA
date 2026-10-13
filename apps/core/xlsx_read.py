"""Đọc tệp xlsx tối giản bằng thư viện chuẩn (không cần openpyxl): liệt kê sheet và đọc từng dòng."""
import re
import zipfile
import xml.etree.ElementTree as ET

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def col_index(ref):
    letters = re.match(r"[A-Z]+", ref).group(0)
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


def sheets(source):
    """source: đường dẫn hoặc đối tượng tệp nhị phân. Trả [(tên sheet, phần xml, zip, chuỗi dùng chung)]."""
    z = zipfile.ZipFile(source)
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    target = {r.get("Id"): r.get("Target") for r in rels}
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))
    out = []
    for sh in wb.find("m:sheets", NS):
        name = sh.get("name")
        rid = sh.get("{%s}id" % NS["r"])
        part = "xl/" + target[rid].lstrip("/").replace("xl/", "")
        out.append((name, part, z, shared))
    return out


def rows(entry, limit=None):
    name, part, z, shared = entry
    with z.open(part) as f:
        for _, el in ET.iterparse(f):
            if el.tag == "{%s}row" % NS["m"]:
                vals = {}
                for c in el.findall("m:c", NS):
                    t = c.get("t")
                    v = c.find("m:v", NS)
                    if t == "inlineStr":
                        val = "".join(x.text or "" for x in c.iter("{%s}t" % NS["m"]))
                    elif t == "s" and v is not None:
                        val = shared[int(v.text)]
                    else:
                        val = v.text if v is not None else ""
                    vals[col_index(c.get("r"))] = val
                n = max(vals) + 1 if vals else 0
                yield [vals.get(i, "") for i in range(n)]
                el.clear()
                if limit is not None:
                    limit -= 1
                    if limit <= 0:
                        return


def part_size(entry):
    return entry[2].getinfo(entry[1]).file_size


def excel_date(value):
    """Số ngày kiểu Excel (gốc 30/12/1899) sang date; không phải số thì trả None."""
    from datetime import date, timedelta

    try:
        return date(1899, 12, 30) + timedelta(days=int(float(value)))
    except (TypeError, ValueError):
        return None
