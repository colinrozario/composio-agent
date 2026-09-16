Independent second opinion. A platform team wants to know how hard it is to connect an AI agent to {name}
({hint}). Answer as a skeptical integration engineer who has been burned by outdated docs.

Questions, answer each from the vendor's current developer pages found by web search:
- How does a developer authenticate? (auth_methods)
- What is the hardest gate before production use: nothing, a paid plan, app/partner review, a sales call,
  or is there no public API at all? (access_path)
- REST, GraphQL, SDK-only, CLI-only, or nothing? (api_type)
- Is there an MCP server published by the vendor itself? (official_mcp)
- Does every customer have their own host/subdomain? (base_url_model)
- Can you test for free? (test_account)

Return ONLY a JSON object keyed by field name, each value shaped {{"value": ..., "confidence": "high|med|low", "source_url": "..."}}
(auth_methods value is an array). Use "unknown" rather than guessing. Allowed values:
{enums}
Fields: auth_methods, access_path, api_type, official_mcp, base_url_model, test_account
