from context.sources.pmc import PMCClient


def test_nested_section_paragraphs_are_emitted_once():
    xml = """
    <article><body><sec>
      <title>Outer</title>
      <p>Outer paragraph.</p>
      <sec><title>Inner</title><p>Inner paragraph.</p></sec>
    </sec></body></article>
    """

    text = PMCClient()._extract_text_from_xml(xml)

    assert text.count("Outer paragraph.") == 1
    assert text.count("Inner paragraph.") == 1
