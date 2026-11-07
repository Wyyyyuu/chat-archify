"""Index saved conversation excerpts without inventing missing identities."""
import hashlib
import json
import re
from collections import defaultdict
from urllib.parse import urlsplit

UUID = r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}'

def verified_original_url(source):
    """Return only source-provided HTTPS task URLs explicitly marked verified."""
    value=source.get('original_url')
    if source.get('original_url_verified') is not True or not isinstance(value,str):
        return ''
    value=value.strip()
    try:
        parsed=urlsplit(value)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:
            return ''
    except ValueError:
        return ''
    return value
# --- Stable identity and conservative parser implementation ----------------
UUID_RE = re.compile(rf"(?i)\b{UUID}\b")
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
_TASK_RE = re.compile(r"^\s*(?:任务|task)\s*ID\s*[:：]\s*(\S+)\s*$", re.I)
_TURN_RE = re.compile(r"^\s*(?:轮次|turn)\s*ID\s*[:：]\s*(\S+)\s*$", re.I)
_MESSAGE_RE = re.compile(r"^\s*(?:消息|message)\s*ID\s*[:：]\s*(\S+)\s*$", re.I)
_TASK_TITLE_RE = re.compile(r'^\s*(?:任务|task)\s*[:：]', re.I)
_LINE_RANGE_RE = re.compile(r"(?i)(?:\bL\s*|行\s*|lines?\s*)(\d+)\s*(?:[-–—~至]\s*(?:L\s*)?(\d+))?")
_MESSAGE_NUMBER_RE = re.compile(r"(?i)(?:第\s*|message\s*#?\s*)(\d+)\s*(?:条|段|message)?")
_ROLE_NAMES = {
    "用户": "用户", "user": "用户", "human": "用户", "request": "用户", "提问": "用户",
    "助手": "助手", "助手交付陈述": "助手", "assistant": "助手", "chatgpt": "助手", "ai": "助手", "回答": "助手",
    "摘要": "摘要", "summary": "摘要", "summarized": "摘要",
}


def _identity_sha(value, length=18):
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:length]


def _identity_normalise(value):
    return re.sub(r"\s+", " ", str(value or "").replace("\r\n", "\n").strip())


def _canonical_role(value):
    raw = str(value or "").strip()
    return _ROLE_NAMES.get(raw.casefold(), raw if raw else "")


def _role_from_heading(title):
    raw = str(title or "").strip()
    tail = re.split(r"(?:·|\||[-–—])", raw)[-1].strip()
    if tail.casefold() in _ROLE_NAMES:
        return _ROLE_NAMES[tail.casefold()]
    if raw.casefold() in _ROLE_NAMES:
        return _ROLE_NAMES[raw.casefold()]
    return ""


def _role_marker(line):
    stripped = str(line or "").strip()
    heading = re.match(r"^#{1,6}\s*(用户|助手|User|Assistant|ChatGPT|Human|AI)\s*:?\s*$", stripped, re.I)
    if heading:
        return _canonical_role(heading.group(1)), ""
    marker = re.match(r"^(?:[-*]\s*)?(?:\d+[.)]\s*)?(用户|助手|User|Assistant|ChatGPT|Human|AI)\s*[:：]\s?(.*)$", stripped, re.I)
    if marker:
        return _canonical_role(marker.group(1)), marker.group(2)
    return "", ""


def _fence_lines(lines):
    in_fence = False
    fences = []
    for line in lines:
        fences.append(in_fence)
        if _FENCE_RE.match(line):
            in_fence = not in_fence
    return fences


def _metadata(lines):
    task = turn = message = ""
    for line in lines:
        if line.strip() and not (_TASK_RE.match(line) or _TURN_RE.match(line) or _MESSAGE_RE.match(line) or _TASK_TITLE_RE.match(line)):
            break
        for pattern, name in ((_TASK_RE, "task"), (_TURN_RE, "turn"), (_MESSAGE_RE, "message")):
            match = pattern.match(line)
            if not match:
                continue
            value = match.group(1).strip().rstrip("；;")
            if name == "task" and not task:
                task = value
            elif name == "turn" and not turn:
                turn = value
            elif name == "message" and not message:
                message = value
    return task, turn, message


def _body_and_range(lines, start_line, strip_metadata=False):
    kept = []
    header = strip_metadata
    for offset, line in enumerate(lines):
        if header and (_TASK_RE.match(line) or _TURN_RE.match(line) or _MESSAGE_RE.match(line) or _TASK_TITLE_RE.match(line)):
            continue
        if line.strip():
            header = False
        kept.append((start_line + offset, line))
    while kept and not kept[0][1].strip():
        kept.pop(0)
    while kept and (not kept[-1][1].strip() or kept[-1][1].strip() == "---"):
        kept.pop()
    if not kept:
        return "", start_line, start_line
    return "\n".join(line for _, line in kept).strip(), kept[0][0], kept[-1][0]


def _header_starts(lines, fences):
    starts = []
    for index, line in enumerate(lines):
        if fences[index] or not re.match(r"^\s*#{1,6}\s+\S", line):
            continue
        if _metadata(lines[index + 1:index + 10])[0]:
            starts.append(index)
    return starts


def _explicit_excerpts(text, task_id):
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    fences = _fence_lines(lines)
    starts = _header_starts(lines, fences)
    result = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        title = re.sub(r"^\s*#{1,6}\s+", "", lines[start]).strip()
        block = lines[start + 1:end]
        task, turn, message = _metadata(block)
        if task_id and task != task_id:
            continue
        body, line_start, line_end = _body_and_range(block, start + 2, strip_metadata=True)
        role = _role_from_heading(title) or ("摘要" if re.search(r"摘要|summary", title, re.I) else "")
        date_match = re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", title)
        date = date_match[0].replace("T", " ") if date_match else ""
        summaries = list(re.finditer(r"^\s*-\s*(?:轮次|turn)\s+([^：:]+)[：:]\s*(.+)$", body, re.M | re.I))
        if summaries and not turn:
            for summary in summaries:
                row_line = line_start + body[:summary.start()].count("\n")
                result.append({"title": title, "role": "摘要", "task_id": task, "turn_id": summary.group(1).strip(),
                              "message_id": "", "text": summary.group(2).strip(), "date": date, "line": row_line,
                              "line_start": row_line, "line_end": row_line, "message_index": len(result) + 1,
                              "_source_kind": "original" if task or summary.group(1).strip() else "local"})
            continue
        result.append({"title": title, "role": role, "task_id": task, "turn_id": turn, "message_id": message,
                       "text": body, "date": date, "line": line_start, "line_start": line_start,
                       "line_end": line_end, "message_index": len(result) + 1,
                       "_source_kind": "original" if task or turn or message else "local"})
    return result


def _generic_role_excerpts(text):
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    fences = _fence_lines(lines)
    starts = []
    for index, line in enumerate(lines):
        if fences[index]:
            continue
        role, inline = _role_marker(line)
        if role:
            starts.append((index, role, inline))
    result = []
    for position, (start, role, inline) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        body, line_start, line_end = _body_and_range(lines[start + 1:end], start + 2)
        line_end = line_end if body else start + 1
        line_start = start + 1
        if inline:
            body = (inline + ("\n" + body if body else "")).strip()
        result.append({"title": lines[start].strip(), "role": role, "task_id": "", "turn_id": "",
                       "message_id": "", "text": body, "date": "", "line": line_start,
                       "line_start": line_start, "line_end": line_end, "message_index": len(result) + 1,
                       "_source_kind": "local"})
    return result


def _json_content(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        for key in ("text", "value", "content", "parts"):
            if key in value:
                content = _json_content(value[key])
                if content:
                    return content
    return ""


def _json_role(message):
    role = message.get("role")
    if role is None and isinstance(message.get("author"), dict):
        role = message["author"].get("role")
    return _canonical_role(role)


def _looks_like_message(value):
    return isinstance(value, dict) and ("content" in value or "parts" in value or "role" in value or isinstance(value.get("author"), dict))


def _collect_json_messages(value, result):
    if isinstance(value, list):
        for item in value:
            if _looks_like_message(item):
                result.append(item)
            else:
                _collect_json_messages(item, result)
        return
    if not isinstance(value, dict):
        return
    if _looks_like_message(value):
        result.append(value)
        return
    if isinstance(value.get("messages"), list):
        _collect_json_messages(value["messages"], result)
        return
    if isinstance(value.get("mapping"), dict):
        for item in value["mapping"].values():
            if isinstance(item, dict) and _looks_like_message(item.get("message")):
                result.append(item["message"])
            else:
                _collect_json_messages(item, result)
        return
    for item in value.values():
        if isinstance(item, (list, dict)):
            _collect_json_messages(item, result)


def _json_excerpts(text):
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return []
    messages = []
    _collect_json_messages(value, messages)
    if not messages:
        return []
    result = []
    for index, message in enumerate(messages, 1):
        body = _json_content(message.get("content", message.get("parts", ""))).strip()
        if not body and isinstance(message.get("text"), str):
            body = message["text"].strip()
        role = _json_role(message)
        task = str(message.get("task_id") or "")
        # Chat-wide conversation_id identifies the source, not a turn.  Only
        # an explicit turn_id may create an original turn group; otherwise
        # messages stay local and are conservatively paired by role.
        turn = str(message.get("turn_id") or "")
        message_id = str(message.get("message_id") or message.get("id") or "")
        result.append({"title": "JSON messages", "role": role, "task_id": task, "turn_id": turn,
                       "message_id": message_id, "text": body, "date": str(message.get("date") or message.get("timestamp") or ""),
                       "line": 0, "line_start": 0, "line_end": 0, "position_kind": "message",
                       "message_index": index, "_source_kind": "original" if task or turn or message_id else "local"})
        if isinstance(message.get('collection_order'), int) and message['collection_order'] >= 0:
            result[-1]['collection_order'] = message['collection_order']
        if isinstance(message.get('source_item_id'), str):
            result[-1]['source_item_id'] = message['source_item_id']
    return result


def _assign_local_groups(parsed):
    anchor_occurrences = defaultdict(int)
    role_numbers = defaultdict(int)
    index = 0
    while index < len(parsed):
        current = parsed[index]
        role = _canonical_role(current.get("role"))
        if role:
            role_numbers[role] += 1
            current["role_message_index"] = role_numbers[role]
        if current.get("turn_id"):
            current["_group_token"] = ("turn", current.get("task_id", ""), current["turn_id"])
            index += 1
            continue
        anchor = ('message:' + str(current.get('task_id') or '') + ':' + str(current['message_id'])) if current.get('message_id') else _identity_normalise(current.get('text'))
        anchor_key = (role, _identity_sha(anchor))
        occurrence = anchor_occurrences[anchor_key]
        anchor_occurrences[anchor_key] += 1
        token = ("local", role, anchor_key[1], occurrence)
        if current.get("role") == "用户" and index + 1 < len(parsed) and parsed[index + 1].get("role") == "助手" and not parsed[index + 1].get('turn_id') and (not current.get('task_id') or not parsed[index + 1].get('task_id') or current['task_id']==parsed[index + 1]['task_id']):
            current["_group_token"] = token
            role_numbers["助手"] += 1
            parsed[index + 1]["role_message_index"] = role_numbers["助手"]
            parsed[index + 1]["_group_token"] = token
            index += 2
            continue
        current["_group_token"] = token
        index += 1


def excerpts(text, task_id=""):
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    parsed = _json_excerpts(text) if text.lstrip().startswith(("{", "[")) else []
    if not parsed:
        parsed = _explicit_excerpts(text, task_id)
    if not parsed:
        parsed = _generic_role_excerpts(text)
    if task_id:
        parsed = [entry for entry in parsed if not entry.get("task_id") or entry.get("task_id") == task_id]
    _assign_local_groups(parsed)
    return parsed


def _source_identity(chapter_id, source, collision=False):
    conversation_id = str(source.get("conversation_id") or "").strip()
    base = "conversation:" + conversation_id if conversation_id else "source:" + str(source.get("id") or "unknown")
    return f"chapter:{chapter_id}:{base}" if collision else base


def _entry_locator_match(entry, locator, known_entries=None):
    locator = str(locator or "")
    precise_id_match = False
    for field, label in [('task_id',r'(?:任务|task)\s*ID'), ('turn_id',r'(?:轮次|turn)\s*(?:ID)?'), ('message_id',r'(?:消息|message)\s*ID')]:
        explicit = set(re.findall(label + r'\s*[:：]\s*([A-Za-z0-9_-]+)', locator, re.I))
        found = {item.get(field) for item in (known_entries or [entry]) if item.get(field) and re.search(rf"(?<![A-Za-z0-9_-]){re.escape(item[field])}(?![A-Za-z0-9_-])", locator)}
        expected = explicit or found
        if expected:
            if entry.get(field) not in expected:
                return False
            if field != 'task_id':
                precise_id_match = True
    ranges = []
    for match in _LINE_RANGE_RE.finditer(locator):
        first = int(match.group(1)); last = int(match.group(2) or first)
        ranges.append((min(first, last), max(first, last)))
    if ranges:
        if entry.get('position_kind') == 'message':
            return False
        first = entry.get("line_start") or entry.get("start_line") or entry.get("line") or 0
        last = entry.get("line_end") or entry.get("end_line") or entry.get("line") or 0
        return any(first <= high and last >= low for low, high in ranges)
    message_numbers = [int(match.group(1)) for match in _MESSAGE_NUMBER_RE.finditer(locator)]
    if not message_numbers:
        # A task identifies a source, not which messages belong to a module.
        return precise_id_match
    role = "用户" if re.search(r"(?:用户|user|human)\s*(?:第|message)", locator, re.I) else "助手" if re.search(r"(?:助手|assistant|chatgpt)\s*(?:第|message)", locator, re.I) else ""
    if not role:
        if re.search(r'(?i)(?:message\s*#|第\s*\d+\s*条消息)', locator):
            return entry.get('message_index') in message_numbers
        # "第 N 条消息" is ambiguous when a transcript contains both sides.
        return False
    return entry.get("role") == role and entry.get("role_message_index") in message_numbers


def _entry_base_identity(source_identity, entry, ordinal):
    task, turn, message = entry.get("task_id") or "", entry.get("turn_id") or "", entry.get("message_id") or ""
    if task:
        source_identity = 'task:' + task
    role = _canonical_role(entry.get("role"))
    if task or turn or message:
        if message:
            return ("original", source_identity, task, turn, message)
        # A turn/message export can omit message_id.  Role plus exact body is
        # the only stable discriminator available; line order is deliberately
        # excluded so moving or appending source text does not rewrite IDs.
        return ("original", source_identity, task, turn, role, _identity_sha(_identity_normalise(entry.get("text"))))
    return ("local", source_identity, _identity_sha(f"{role}\x1f{_identity_normalise(entry.get('text'))}"), ordinal)


def _source_occurrences(chapters):
    seen = defaultdict(list)
    for chapter in chapters:
        for source in chapter.get("record", {}).get("sources", []):
            if source.get("kind") != "conversation":
                continue
            signature = (source.get("id"), source.get("conversation_id"), source.get("file_id") or source.get("uri"))
            seen[source.get("id")].append((chapter.get("id"), signature))
    result = {}
    for source_id, occurrences in seen.items():
        signatures = {signature for _, signature in occurrences}
        for chapter_id, _signature in occurrences:
            result[(chapter_id, source_id)] = len(signatures) > 1
    return result


def build_conversation_index(chapters, files):
    entries = {}
    source_occurrence = _source_occurrences(chapters)
    for chapter in chapters:
        chapter_id = chapter["id"]
        sources = {s["id"]: s for s in chapter["record"]["sources"]}
        for source in sources.values():
            if source["kind"] != "conversation":
                continue
            file = files.get(source.get("file_id"))
            source["conversation_entry_ids"] = []
            identity = _source_identity(chapter_id, source, source_occurrence.get((chapter_id, source.get("id")), False))
            source["conversation_source_identity"] = identity
            if not file or not isinstance(file.get("text"), str):
                continue
            task_match = UUID_RE.search(str(source.get("locator", "")))
            task = task_match[0] if task_match else ""
            parsed = excerpts(file["text"], task)
            if not parsed and not task:
                parsed = [{"title": source["title"], "role": "", "date": "", "task_id": "", "turn_id": "", "message_id": "",
                           "text": file["text"], "line": 1, "line_start": 1,
                           "line_end": max(1, file["text"].count("\n") + 1), "message_index": 1,
                           "_source_kind": "local", "_group_token": ("local", 1)}]
            _assign_local_groups(parsed)
            ordinal_counts = defaultdict(int)
            for excerpt in parsed:
                duplicate_key = (_canonical_role(excerpt.get("role")), excerpt.get("task_id", ""), excerpt.get("turn_id", ""), excerpt.get("message_id", ""), _identity_normalise(excerpt.get("text")))
                ordinal = ordinal_counts[duplicate_key]
                ordinal_counts[duplicate_key] += 1
                base = _entry_base_identity(identity, excerpt, ordinal)
                if ordinal:
                    base = (*base, ordinal)
                key = "conversation_" + _identity_sha("\x1f".join(map(str, base)))
                # Older exports recorded provider item-N as message IDs. Reuse
                # that saved entry only when the provider item and exact body
                # agree; do not duplicate it or invent a new native message ID.
                item_id = excerpt.get('source_item_id', '')
                if not excerpt.get('message_id') and re.fullmatch(r'item-\d+', item_id):
                    legacy = [e for e in entries.values() if e.get('message_id') == item_id
                              and e.get('task_id') == excerpt.get('task_id') and e.get('turn_id') == excerpt.get('turn_id')
                              and e.get('role') == excerpt.get('role') and _identity_normalise(e.get('text')) == _identity_normalise(excerpt.get('text'))]
                    if len(legacy) == 1:
                        key = legacy[0]['id']
                if excerpt.get("turn_id"):
                    group_base = ("turn", 'task:' + excerpt['task_id'] if excerpt.get('task_id') else identity, excerpt.get("task_id", ""), excerpt.get("turn_id", ""))
                else:
                    group_base = ("local", identity, excerpt.get("_group_token"))
                identity_kind = "original" if excerpt.get("task_id") or excerpt.get("turn_id") or excerpt.get("message_id") else "local"
                group_id = ("turn_" if excerpt.get('turn_id') else "local_") + _identity_sha("\x1f".join(map(str, group_base)))
                if key not in entries:
                    original_url = verified_original_url(source)
                    entries[key] = {**{k: v for k, v in excerpt.items() if not k.startswith("_")}, "id": key,
                                    "identity_kind": identity_kind,
                                    "group_identity_kind": 'original' if excerpt.get('turn_id') else 'local',
                                    "identity_note": "源记录 ID 生成" if identity_kind == "original" else "本地来源与正文生成标识；原始任务/轮次/消息 ID 未记录",
                                    "source_identity": identity,
                                    "local_identity": "local_" + _identity_sha(f"{identity}\x1f{_identity_normalise(excerpt.get('text'))}\x1f{excerpt.get('role', '')}\x1f{ordinal}") if identity_kind == "local" else "",
                                    "source_title": source["title"], "file_id": file["id"], "source_locator": source["locator"],
                                    "coverage": source["coverage"], "nodes": [], "original_url": original_url,
                                    "original_url_verified": bool(original_url), "turn_group_id": group_id}
                    entries[key]["start_line"] = entries[key].get("line_start", entries[key].get("line", 1))
                    entries[key]["end_line"] = entries[key].get("line_end", entries[key].get("line", 1))
                    entries[key]["line_range"] = '' if excerpt.get('position_kind') == 'message' else f"L{entries[key].get('line_start', entries[key].get('line', 1))}-L{entries[key].get('line_end', entries[key].get('line', 1))}"
                if 'collection_order' in excerpt:
                    entries[key]['collection_order'] = excerpt['collection_order']
                source["conversation_entry_ids"].append(key)
        for node in chapter["record"]["nodes"]:
            refs, available = [], []
            for evidence in node["evidence"]:
                source = sources[evidence["source"]]
                if source["kind"] != "conversation":
                    continue
                candidates = source.get("conversation_entry_ids", [])
                available.extend(candidates)
                refs.extend(key for key in candidates if _entry_locator_match(entries[key], evidence.get("locator", ""), [entries[item] for item in candidates]))
            node["conversation_entry_ids"] = list(dict.fromkeys(refs))
            node["conversation_source_entry_ids"] = list(dict.fromkeys(available))
            for key in node["conversation_entry_ids"]:
                entries[key]["nodes"].append({"chapter": chapter_id, "node": node["id"], "title": node["title"]})
    by_source_task = defaultdict(list); by_group = defaultdict(list)
    for entry in entries.values():
        by_source_task[(entry.get("source_identity", ""), entry.get("task_id", ""))].append(entry)
        by_group[entry.get("turn_group_id", entry["id"])].append(entry)
    for group in by_group.values():
        collected = any('collection_order' in e for e in group)
        group.sort(key=lambda e: (e.get('collection_order', float('inf')) if collected else e.get("message_index") or 0,
                                  e.get("line_start") or e.get("line") or 0, e["id"]))
        for index, entry in enumerate(group):
            entry['conversation_order'] = index
        ids = [e["id"] for e in group]
        for entry in group:
            entry["turn_entry_ids"] = ids
    for group in by_source_task.values():
        group.sort(key=lambda e: (e.get("message_index") or 0, e.get("line_start") or e.get("line") or 0, e["id"]))
        for index, entry in enumerate(group):
            entry["context_entry_ids"] = [e["id"] for e in group[max(0, index - 1):index] + group[index + 1:index + 2]]
    return list(entries.values())


def _migration_source_key(entry):
    if entry.get("source_identity"):
        return str(entry["source_identity"])
    if entry.get("task_id"):
        return "task:" + str(entry["task_id"])
    return "source:" + str(entry.get("source_title") or entry.get("source_locator") or "")


def _entry_original_key(entry):
    if not any(entry.get(key) for key in ("task_id", "turn_id", "message_id")):
        return None
    message = entry.get("message_id", "")
    body = "" if message else _identity_sha(_identity_normalise(entry.get("text")))
    return (_migration_source_key(entry), entry.get("task_id", ""), entry.get("turn_id", ""), message, _canonical_role(entry.get("role")), body)


def _entry_global_original_key(entry):
    key = _entry_original_key(entry)
    if key is None:
        return None
    return key[1:]


def _entry_local_key(entry):
    if any(entry.get(key) for key in ("task_id", "turn_id", "message_id")):
        return None
    return (_migration_source_key(entry), _canonical_role(entry.get("role")), _identity_normalise(entry.get("text")))


def build_conversation_aliases(previous_payload, current_entries):
    """Build uniquely verifiable old-ID -> current-ID aliases."""
    old_entries = list((previous_payload or {}).get("conversations") or [])
    current_entries = list(current_entries or [])
    old_by_original = defaultdict(list); current_by_original = defaultdict(list)
    old_by_global_original = defaultdict(list); current_by_global_original = defaultdict(list)
    old_by_local = defaultdict(list); current_by_local = defaultdict(list)
    old_by_global_local = defaultdict(list); current_by_global_local = defaultdict(list)
    for entry in old_entries:
        key = _entry_original_key(entry)
        if key:
            old_by_original[key].append(entry);old_by_global_original[_entry_global_original_key(entry)].append(entry)
        else:
            local=_entry_local_key(entry);old_by_local[local].append(entry);old_by_global_local[local[1:]].append(entry)
    for entry in current_entries:
        key = _entry_original_key(entry)
        if key:
            current_by_original[key].append(entry);current_by_global_original[_entry_global_original_key(entry)].append(entry)
        else:
            local=_entry_local_key(entry);current_by_local[local].append(entry);current_by_global_local[local[1:]].append(entry)
    entry_aliases = {}
    target_to_old = {}
    current_by_id = {str(entry.get('id')): entry for entry in current_entries}
    for old in old_entries:
        key = _entry_original_key(old)
        direct = current_by_id.get(str(old.get('id')))
        if direct and ((_entry_original_key(direct) == key) if key else (_entry_local_key(direct) == _entry_local_key(old))):
            candidates = [direct]
        elif key:
            candidates = current_by_original.get(key, []) or current_by_global_original.get(_entry_global_original_key(old), [])
        else:
            local = _entry_local_key(old);candidates = current_by_local.get(local, []) or current_by_global_local.get(local[1:], [])
        if len(candidates) > 1:
            raise ValueError(f"Ambiguous conversation identity migration for {old.get('id', '')}")
        if candidates:
            old_id, target_id = str(old.get("id")), str(candidates[0].get("id"))
            if target_id in target_to_old and target_to_old[target_id] != old_id:
                raise ValueError(f"Ambiguous conversation identity migration for {old_id}")
            target_to_old[target_id] = old_id
            entry_aliases[old_id] = target_id
    old_groups = defaultdict(list); current_groups = defaultdict(list)
    for entry in old_entries:
        old_groups[str(entry.get("turn_group_id") or entry.get("id"))].append(entry)
    for entry in current_entries:
        current_groups[str(entry.get("turn_group_id") or entry.get("id"))].append(entry)
    by_current_id = {str(entry.get("id")): entry for entry in current_entries}
    group_aliases = {}
    group_target_to_old = {}
    for old_group_id, members in old_groups.items():
        mapped = {entry_aliases.get(str(member.get("id"))) for member in members}; mapped.discard(None)
        if len(mapped) != len(members):
            mapped = set()
        target_ids = {str(by_current_id[item].get("turn_group_id") or item) for item in mapped if item in by_current_id}
        if len(target_ids) > 1:
            raise ValueError(f"Ambiguous conversation group migration for {old_group_id}")
        if target_ids:
            target_id = next(iter(target_ids))
            if target_id in group_target_to_old and group_target_to_old[target_id] != old_group_id:
                raise ValueError(f"Ambiguous conversation group migration for {old_group_id}")
            group_target_to_old[target_id] = old_group_id
            group_aliases[old_group_id] = target_id; continue
        signatures = {_entry_original_key(member) or _entry_local_key(member) for member in members}
        candidates = []
        for current_id, current_members in current_groups.items():
            current_signatures = {_entry_original_key(member) or _entry_local_key(member) for member in current_members}
            if signatures and signatures == current_signatures:
                candidates.append(current_id)
        if len(candidates) > 1:
            raise ValueError(f"Ambiguous conversation group migration for {old_group_id}")
        if candidates:
            target_id = candidates[0]
            if target_id in group_target_to_old and group_target_to_old[target_id] != old_group_id:
                raise ValueError(f"Ambiguous conversation group migration for {old_group_id}")
            group_target_to_old[target_id] = old_group_id
            group_aliases[old_group_id] = target_id
    return group_aliases, entry_aliases
