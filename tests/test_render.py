import logifos


def test_render_refuses_until_the_engine_lands():
    try:
        logifos.render({})
        raise AssertionError("render should refuse")
    except NotImplementedError as error:
        assert "engine boundary lands" in str(error)
