"""The file operations the assistant may run, read from Stirling-PDF's own OpenAPI document."""
import json
import re

# Operations left out on purpose: anything that fetches content from the internet (Stirling can reach the
# local network), signing with certificates, the in-browser editor, and job plumbing.
DENY = re.compile(r"(text-editor|cert-sign|/jobs/|convert/url/|convert/html/|convert/markdown/pdf|convert/eml/"
                  r"|timestamp-pdf|show-javascript|encode-charcodes|/vector/pdf|batch-process|create-portfolio)")


def parse(doc):
    comps = doc.get("components", {}).get("schemas", {})

    def res(x):
        return comps[x["$ref"].split("/")[-1]] if "$ref" in x else x

    out = {}
    for path, methods in doc.get("paths", {}).items():
        o = methods.get("post")
        m = re.match(r"^/api/v1/(general|convert|misc|security)/(.+)$", path)
        if not o or not m or DENY.search(path) or "{" in path:
            continue
        content = o.get("requestBody", {}).get("content", {}).get("multipart/form-data")
        if not content:
            continue
        schema = res(content["schema"])
        file_field, multi, params = None, False, {}
        for k, p in (schema.get("properties") or {}).items():
            p = res(p)
            items = p.get("items") or {}
            if p.get("format") == "binary" or items.get("format") == "binary":
                if file_field is None:
                    file_field, multi = k, p.get("type") == "array"
                continue
            if k in ("fileId", "clientFileIds"):
                continue
            spec = {x: p.get(x) for x in ("type", "enum", "default") if p.get(x) is not None}
            if p.get("description"):
                spec["desc"] = re.sub(r"\s+", " ", p["description"])[:110]
            params[k] = spec
        if not file_field:
            continue
        out[path[len("/api/v1/"):]] = {
            "path": path, "summary": (o.get("summary") or "").strip(), "file_field": file_field, "multi": multi,
            "params": params, "required": schema.get("required") or []}
    return out


def describe(catalog, query):
    q = (query or "").lower().strip()
    if not catalog:
        return "File tools are not set up on this server."
    if not q or q in ("all", "list", "*"):
        return ("File operations (name: summary). Call pdf_operations again with a name or word to get its "
                "parameters.\n" + "\n".join("%s: %s" % (k, v["summary"]) for k, v in sorted(catalog.items())))
    words = [w for w in re.split(r"[\s,/]+", q) if w]
    hits = [k for k, v in catalog.items() if all(w in (k + " " + v["summary"]).lower() for w in words)]
    if not hits:
        hits = [k for k, v in catalog.items() if any(w in (k + " " + v["summary"]).lower() for w in words)]
    if not hits:
        return "No operation matches %r. Call pdf_operations with an empty query to list all." % query
    out = []
    for k in sorted(hits)[:6]:
        v = catalog[k]
        lines = ["operation: %s  (%s)  files: %s" % (k, v["summary"], "one or more" if v["multi"] else "exactly one")]
        for p, spec in v["params"].items():
            lines.append("  - %s%s: %s" % (p, " (required)" if p in v["required"] else "",
                                          json.dumps(spec, ensure_ascii=False)))
        out.append("\n".join(lines))
    return "\n\n".join(out)
