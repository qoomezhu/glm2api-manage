from glm2api.utils.tool_parser import StreamingToolParser, parse_tool_calls_from_text


def test_parse_tool_calls_from_dsml_markup():
    text = (
        "before\n"
        "<dsml-tool-calls>\n"
        '  <dsml-invoke name="get_weather">\n'
        '    <dsml-parameter name="city"><![CDATA[上海]]></dsml-parameter>\n'
        '    <dsml-parameter name="days">2</dsml-parameter>\n'
        "  </dsml-invoke>\n"
        "</dsml-tool-calls>\n"
        "after"
    )

    clean, tool_calls = parse_tool_calls_from_text(text, {"get_weather"})

    assert clean == "before\n\nafter"
    assert len(tool_calls) == 1
    assert tool_calls[0]["function"]["name"] == "get_weather"
    assert tool_calls[0]["function"]["arguments"] == '{"city":"上海","days":2}'


def test_parse_tool_calls_from_canonical_invoke_markup():
    text = (
        "<tool_calls><invoke name=\"search_web\">"
        "<parameter name=\"query\"><![CDATA[glm2api]]></parameter>"
        "<parameter name=\"filters\"><parameter name=\"site\">example.com</parameter></parameter>"
        "<parameter name=\"tags\"><item>python</item><item>xml</item></parameter>"
        "</invoke></tool_calls>"
    )

    clean, tool_calls = parse_tool_calls_from_text(text, {"search_web"})

    assert clean == ""
    assert len(tool_calls) == 1
    assert tool_calls[0]["function"]["arguments"] == (
        '{"query":"glm2api","filters":{"site":"example.com"},"tags":["python","xml"]}'
    )


def test_parse_rejects_undeclared_and_blocked_native_tools():
    blocked_text = (
        "<dsml-tool-calls>\n"
        '  <dsml-invoke name="open_url">\n'
        '    <dsml-parameter name="url"><![CDATA[https://example.com]]></dsml-parameter>\n'
        "  </dsml-invoke>\n"
        "</dsml-tool-calls>"
    )
    undeclared_text = (
        "<dsml-tool-calls>\n"
        '  <dsml-invoke name="not_declared">\n'
        '    <dsml-parameter name="value">x</dsml-parameter>\n'
        "  </dsml-invoke>\n"
        "</dsml-tool-calls>"
    )

    clean, tool_calls = parse_tool_calls_from_text(blocked_text, {"open_url"})
    assert clean == ""
    assert tool_calls == []

    clean, tool_calls = parse_tool_calls_from_text(undeclared_text, {"allowed_tool"})
    assert clean == ""
    assert tool_calls == []


def test_parse_ignores_dsml_markup_inside_code_fence():
    text = (
        "```xml\n"
        "<dsml-tool-calls>\n"
        '  <dsml-invoke name="get_weather"></dsml-invoke>\n'
        "</dsml-tool-calls>\n"
        "```"
    )

    clean, tool_calls = parse_tool_calls_from_text(text, {"get_weather"})

    assert clean == text
    assert tool_calls == []


def test_streaming_tool_parser_never_leaks_dsml_markup_fragments():
    parser = StreamingToolParser(allowed_tool_names={"get_weather"})
    visible_parts: list[str] = []
    payload = (
        "<dsml-tool-calls>\n"
        '  <dsml-invoke name="get_weather">\n'
        '    <dsml-parameter name="city"><![CDATA[上海]]></dsml-parameter>\n'
        "  </dsml-invoke>\n"
        "</dsml-tool-calls>"
    )

    for char in payload:
        piece = parser.consume(char)
        visible_parts.append(piece)
        assert "<dsml-" not in piece
        assert "</dsml-" not in piece

    tail, tool_calls = parser.flush()

    assert "".join(visible_parts) == ""
    assert tail == ""
    assert len(tool_calls) == 1
    assert tool_calls[0]["function"]["arguments"] == '{"city":"上海"}'


def test_parse_tool_calls_parses_json_array_cdata():
    text = (
        "<dsml-tool-calls>\n"
        '  <dsml-invoke name="shell">\n'
        '    <dsml-parameter name="command"><![CDATA[["powershell.exe", "-Command", "pwd"]]]></dsml-parameter>\n'
        "  </dsml-invoke>\n"
        "</dsml-tool-calls>"
    )

    clean, tool_calls = parse_tool_calls_from_text(text, {"shell"})

    assert clean == ""
    assert len(tool_calls) == 1
    assert tool_calls[0]["function"]["arguments"] == '{"command":["powershell.exe","-Command","pwd"]}'


def test_parse_tool_calls_from_xml_markup():
    text = (
        "开始\n"
        "<ml_tool_calls><ml_tool_call><ml_tool_name>get_weather</ml_tool_name>"
        "<ml_parameters><city><![CDATA[上海]]></city><days>2</days></ml_parameters>"
        "</ml_tool_call></ml_tool_calls>\n"
        "结束"
    )

    clean, tool_calls = parse_tool_calls_from_text(text, {"get_weather"})

    assert clean == "开始\n\n结束"
    assert len(tool_calls) == 1
    assert tool_calls[0]["function"]["name"] == "get_weather"
    assert tool_calls[0]["function"]["arguments"] == '{"city":"上海","days":2}'


def test_parse_tool_calls_supports_nested_objects_and_arrays():
    text = (
        "<ml_tool_calls><ml_tool_call><ml_tool_name>search_web</ml_tool_name><ml_parameters>"
        "<query>glm2api</query>"
        "<filters><site>example.com</site><after>2026-01-01</after></filters>"
        "<tags><item>python</item><item>xml</item></tags>"
        "</ml_parameters></ml_tool_call></ml_tool_calls>"
    )

    clean, tool_calls = parse_tool_calls_from_text(text, {"search_web"})

    assert clean == ""
    assert len(tool_calls) == 1
    assert tool_calls[0]["function"]["arguments"] == (
        '{"query":"glm2api","filters":{"site":"example.com","after":"2026-01-01"},"tags":["python","xml"]}'
    )


def test_parse_ignores_tool_markup_inside_code_fence():
    text = (
        "```xml\n"
        "<ml_tool_calls><ml_tool_call><ml_tool_name>get_weather</ml_tool_name></ml_tool_call></ml_tool_calls>\n"
        "```"
    )

    clean, tool_calls = parse_tool_calls_from_text(text, {"get_weather"})

    assert clean == text
    assert tool_calls == []


def test_streaming_tool_parser_hides_complete_tool_block():
    parser = StreamingToolParser(allowed_tool_names={"get_weather"})

    first = parser.consume("你好<ml_tool_calls><ml_tool_call><ml_tool_name>get_weather</ml_tool_name>")
    second = parser.consume("<ml_parameters><city>上海</city></ml_parameters></ml_tool_call></ml_tool_calls>世界")
    tail, tool_calls = parser.flush()

    assert first == "你好"
    assert second == "世界"
    assert tail == ""
    assert len(tool_calls) == 1
    assert tool_calls[0]["function"]["arguments"] == '{"city":"上海"}'


def test_streaming_tool_parser_never_leaks_ml_markup_fragments():
    parser = StreamingToolParser(allowed_tool_names={"mcp__CherryFetch__fetchJson"})
    visible_parts: list[str] = []
    payload = "<ml_tool_calls></ml_tool_calls>"

    for char in payload:
        piece = parser.consume(char)
        visible_parts.append(piece)
        assert "<ml" not in piece
        assert "</ml" not in piece
        assert piece != ">"

    tail, tool_calls = parser.flush()

    assert "".join(visible_parts) == ""
    assert tail == ""
    assert tool_calls == []


def test_parse_rejects_legacy_or_noncanonical_tool_markup():
    # 这些格式不在 START_TAG_PATTERN 支持范围内，应原样保留不解析。
    # 注意：<tool_call> 现在已是受支持的标签名，不再属于"非规范"格式。
    legacy_variants = [
        "<function_call>Bash</function_call>",
        '<invoke name="Bash"><parameters><command>pwd</command></parameters></invoke>',
        '<tool_use><function name="Bash"><parameter name="command">pwd</parameter></function></tool_use>',
    ]

    for markup in legacy_variants:
        clean, tool_calls = parse_tool_calls_from_text(markup, {"Bash"})
        assert clean == markup
        assert tool_calls == []


def test_parse_rejects_tool_call_missing_parameters():
    text = (
        "<ml_tool_calls>"
        "<ml_tool_call><ml_tool_name>search_web</ml_tool_name></ml_tool_call>"
        "</ml_tool_calls>"
    )

    clean, tool_calls = parse_tool_calls_from_text(text, {"search_web"})

    assert clean == ""
    assert tool_calls == []


def test_parse_salvages_malformed_tool_calls_root_without_rewriting_model_text():
    text = (
        "open_url工具被阻止，无法使用。让我改用 fetchJson 工具来访问这个 API："
        "非常抱歉，我之前反复调用了被阻止的工具。"
        "<ml_tool_calls>\n"
        "<ml_tool_name>mcp__CherryFetch__fetchJson</ml_tool_name>\n"
        "<param_name>url</param_name>\n"
        "<param_value>https://example.com/data.json</param_value>\n"
        "</ml_tool_calls>"
    )

    clean, tool_calls = parse_tool_calls_from_text(text, {"mcp__CherryFetch__fetchJson"})

    assert "open_url" in clean
    assert len(tool_calls) == 1
    assert tool_calls[0]["function"]["name"] == "mcp__CherryFetch__fetchJson"
    assert tool_calls[0]["function"]["arguments"] == '{"url":"https://example.com/data.json"}'


def test_parse_salvages_malformed_tool_calls_root_with_empty_params():
    text = (
        "<ml_tool_calls>\n"
        "<ml_tool_name>mcp__CherryFetch__fetchJson</ml_tool_name>\n"
        "<param_name></param_name>\n"
        "<param_value></param_value>\n"
        "</ml_tool_calls>"
    )

    clean, tool_calls = parse_tool_calls_from_text(text, {"mcp__CherryFetch__fetchJson"})

    assert clean == ""
    assert tool_calls == []


def test_parse_hides_empty_ml_tool_calls_shell_without_leaking():
    text = "前缀<ml_tool_calls></ml_tool_calls>后缀"

    clean, tool_calls = parse_tool_calls_from_text(text, {"mcp__CherryFetch__fetchJson"})

    assert clean == "前缀后缀"
    assert tool_calls == []


def test_parse_extracts_param_name_only_payload_for_later_repair():
    text = (
        "<ml_tool_calls>"
        "<ml_tool_call>"
        "<ml_tool_name>mcp__CherryFetch__fetchJson</ml_tool_name>"
        "<ml_parameters><param_name><![CDATA[url]]></param_name></ml_parameters>"
        "</ml_tool_call>"
        "</ml_tool_calls>"
    )

    clean, tool_calls = parse_tool_calls_from_text(text, {"mcp__CherryFetch__fetchJson"})

    assert clean == ""
    assert len(tool_calls) == 1
    assert tool_calls[0]["function"]["arguments"] == '{"param_name":"url"}'
