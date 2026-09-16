You are verifying research about ONE app. You have NO web access and must NOT use prior knowledge.
Use ONLY the page text below. If the pages do not state something, the answer is "unknown".

App: {name}
Fields to re-decide: {fields}

Previous answer (may be wrong, do not trust it):
{previous}

Pages fetched just now (url, then extracted text, truncated):
{pages}

Same enums and field semantics as the original schema:
{enums}

For each field in "Fields to re-decide", return:
{{"value": ..., "confidence": "high|med|low", "source_url": "<one of the URLs above or null>",
  "evidence_quote": "<verbatim snippet under 25 words from that page, or null>", "changed": true|false}}

A value is only "high" if evidence_quote directly states it. Return ONLY a JSON object keyed by field name.
