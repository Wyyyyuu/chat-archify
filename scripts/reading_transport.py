"""Lossless repeated-text references for one self-contained reading pack.

No semantic filtering: every occurrence keeps its role, unit, ref and order.
The JSON map can reconstruct every body byte-for-byte without model judgement.
"""
import re
from collections import Counter

VERSION = 'exact-text-references-v1'
MIN_CHARS = 100


def paragraphs(text):
    return [part for part in re.split(r'(\n\s*\n)', text) if part]


def encode(entries):
    counts = Counter(entry['text'] for entry in entries)
    # Short strings cost less to repeat. Never normalize whitespace or punctuation.
    whole = {text for text, n in counts.items() if n > 1 and len(text) >= MIN_CHARS}
    blocks = Counter(part for text in counts if text not in whole for part in paragraphs(text))
    reusable = whole | {part for part, n in blocks.items() if n > 1 and len(part) >= MIN_CHARS}
    dictionary, identities, encoded = {}, {}, []
    for entry in entries:
        parts = []
        for part in [entry['text']] if entry['text'] in whole else paragraphs(entry['text']):
            if part in reusable:
                if part not in identities:
                    identity = 'B' + str(len(dictionary) + 1)
                    identities[part] = identity
                    dictionary[identity] = part
                parts.append({'ref': identities[part]})
            else:
                parts.append({'text': part})
        encoded.append({**{k:v for k,v in entry.items() if k != 'text'}, 'parts': parts})
    result = {'version': VERSION, 'dictionary': dictionary, 'entries': encoded}
    if decode(result) != entries:
        raise ValueError('Reading transport did not preserve every message')
    return result


def decode(transport):
    return [{**{k:v for k,v in entry.items() if k != 'parts'}, 'text': ''.join(
        transport['dictionary'][part['ref']] if 'ref' in part else part['text'] for part in entry['parts'])}
        for entry in transport['entries']]


def render(transport):
    """Definitions occur inline on first use; later refs never cross pack files."""
    seen, rendered = set(), []
    for entry in transport['entries']:
        parts = []
        for part in entry['parts']:
            if 'text' in part:
                parts.append(part['text'])
            else:
                identity = part['ref']
                if identity in seen:
                    parts.append(f'\n〔同文 {identity}〕\n')
                else:
                    seen.add(identity)
                    parts.append(f'\n〔{identity}〕\n{transport["dictionary"][identity]}\n〔/{identity}〕\n')
        rendered.append(''.join(parts))
    return rendered
