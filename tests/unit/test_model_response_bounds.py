import pytest

from app.services import diagnosis_selection, evidence


@pytest.mark.parametrize("module", [evidence, diagnosis_selection], ids=["qa", "diagnosis"])
@pytest.mark.parametrize("raw", [b"REMOTE_SECRET" * 20000, b"REMOTE_SECRET-not-json",
                                 b'{"choices":null}', b'{"choices":[{"message":null}]}',
                                 b'{"choices":[{"message":{"content":[]}}]}'],
                         ids=["oversized", "malformed", "null-choices", "null-message", "invalid-content"])
def test_invalid_remote_response_is_bounded_and_not_exposed(monkeypatch, module, raw):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-placeholder")
    reads = []
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self, size):
            reads.append(size)
            return raw[:size]
    monkeypatch.setattr(module, "urlopen", lambda *args, **kwargs: Response())
    with pytest.raises(RuntimeError) as caught:
        if module is evidence:
            module.select_with_deepseek("模拟问题", [])
        else:
            module.request_selection({"question": "模拟问题", "evidence": [], "recommendations": []})
    assert reads == [131073]
    assert "REMOTE_SECRET" not in str(caught.value)
    assert "test-only-placeholder" not in str(caught.value)
