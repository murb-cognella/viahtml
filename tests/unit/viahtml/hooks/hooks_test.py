from unittest.mock import create_autospec, patch, sentinel

import pytest
from h_matchers import Any
from pywb.apps.wbrequestresponse import WbResponse
from warcio.statusandheaders import StatusAndHeaders

from viahtml.context import Context
from viahtml.hooks import Hooks


class TestHooks:
    def test_template_vars(self, hooks):
        assert hooks.template_vars == {
            "client_params": Any.function(),
            "external_link_mode": Any.function(),
            "h_embed_url": sentinel.h_embed_url,
            "ignore_prefixes": hooks.ignore_prefixes,
        }

    def test_client_params_in_template_vars(self, hooks):
        with patch.object(hooks, "get_config") as get_config:
            get_config.return_value = ["via", "client"]
            client_params = hooks.template_vars["client_params"]

            params = client_params(sentinel.http_env)

            assert params == "client"
            get_config.assert_called_once_with(sentinel.http_env)

    @pytest.mark.parametrize(
        "link_mode,expected",
        (
            ("new-tab", "new-tab"),
            ("same-tab", "same-tab"),
            (None, "same-tab"),
            ("random", "random"),
        ),
    )
    def test_external_link_mode_in_template_vars(self, hooks, link_mode, expected):
        http_env = {}
        if link_mode is not None:
            http_env["QUERY_STRING"] = f"via.external_link_mode={link_mode}"

        external_link_mode = hooks.template_vars["external_link_mode"]

        assert external_link_mode(http_env) == expected

    def test_ignore_prefixes(self, hooks):
        assert hooks.ignore_prefixes == sentinel.prefixes

    def test_get_config(self, Configuration, hooks):
        config = hooks.get_config(sentinel.http_env)

        Configuration.extract_from_wsgi_environment.assert_called_once_with(
            sentinel.http_env
        )
        assert config == Configuration.extract_from_wsgi_environment.return_value

    def test_get_upstream_url(self, hooks, Configuration):
        config = hooks.get_upstream_url(sentinel.doc_url)

        Configuration.strip_from_url.assert_called_once_with(sentinel.doc_url)
        assert config == Configuration.strip_from_url.return_value

    @pytest.mark.parametrize(
        "status_line",
        (
            "301 Moved Permanently",
            "302 Found",
            "303 See Other",
            "305 Use Proxy",
            "307 Temporary Redirect",
            "308 Permanent Redirect",
        ),
    )
    def test_modify_render_response_rewrites_redirects(
        self, hooks, wb_response, status_line
    ):
        wb_response.status_headers.statusline = status_line
        original_location = "http://via/proxy/http://example.com"
        wb_response.status_headers.add_header("Location", original_location)

        response = hooks.modify_render_response(wb_response)

        location = response.status_headers.get_header("Location")
        hooks.context.make_absolute.assert_called_once_with(original_location)
        assert location == "http://via/proxy/http://example.com"

    def test_modify_render_response_preserves_via_params_on_redirect(
        self, hooks, wb_response, context
    ):
        context.http_environ = {"QUERY_STRING": "via.option=foo"}
        wb_response.status_headers.statusline = "307 Temporary Redirect"
        wb_response.status_headers.add_header("Location", "http://example.com")

        response = hooks.modify_render_response(wb_response)

        location = response.status_headers.get_header("Location")

        assert location == Any.url.containing_query({"via.option": "foo"})

    def test_modify_render_response_survives_no_location(self, hooks, wb_response):
        wb_response.status_headers.statusline = "307 Temporary Redirect"

        response = hooks.modify_render_response(wb_response)

        assert response == wb_response

    @pytest.mark.parametrize(
        "status_line",
        (
            "304 Not Modified",
            "200 Ok",
        ),
    )
    def test_modify_render_response_does_not_modify_other_requests(
        self, hooks, status_line, wb_response
    ):
        wb_response.status_headers.statusline = status_line
        wb_response.status_headers.add_header("Location", "foo")

        response = hooks.modify_render_response(wb_response)

        location = response.status_headers.get_header("Location")
        assert location == "foo"

    @pytest.mark.parametrize(
        "tag,attrs,expected_new_attrs,expected_stop",
        (
            # When we have an <a> tag we make the tag's href absolute (to make
            # sure that requests for the href's URL are not proxied through
            # Via) and return stop=True to prevent pywb from rewriting the href
            # to be proxied through Via.
            (
                "a",
                [("href", "foo"), ("a", "b")],
                [("href", "ABS:foo"), ("a", "b")],
                True,
            ),
            # In all other cases we return stop=False to allow pywb's usual
            # rewriting to happen.
            ("h1", [], [], False),
            # We replace referrerpolicy attrs with "no-referrer-when-downgrade"
            # to prevent third-party sites from blocking the Referer header.
            (
                "img",
                [("referrerpolicy", "no-referrer")],
                [("referrerpolicy", "no-referrer-when-downgrade")],
                False,
            ),
            (
                "img",
                [("referrerpolicy", "no-referrer")],
                [("referrerpolicy", "no-referrer-when-downgrade")],
                False,
            ),
            # Check we prevent rewriting of Canonical URLs
            ("link", [("rel", "canonical")], [("rel", "canonical")], True),
            # And we leave other types of link alone
            ("link", [("rel", "style")], [("rel", "style")], False),
        ),
    )
    def test_modify_tag_attrs_disables_rewriting(
        self, hooks, tag, attrs, expected_new_attrs, expected_stop
    ):  # pylint: disable=too-many-arguments
        hooks.context.make_absolute.side_effect = (
            lambda url, proxy=True, rewrite_fragments=True: "ABS:" + url
        )

        new_attrs, stop = hooks.modify_tag_attrs(tag, attrs)

        assert new_attrs == expected_new_attrs
        assert stop == expected_stop

    def test_modify_tag_attrs_passes_expected_absolute_args(self, hooks):
        # We're just confirming we call `make_absolute()` with the right stuff
        hooks.modify_tag_attrs("a", [("href", "url")])

        hooks.context.make_absolute.assert_called_once_with(
            "url", proxy=False, rewrite_fragments=False
        )

    @pytest.fixture
    def wb_response(self):
        return WbResponse(status_headers=StatusAndHeaders("200 OK", headers=[]))

    @pytest.fixture
    def context(self):
        context = create_autospec(Context, spec_set=True, instance=True)
        context.host = "via"
        context.make_absolute.side_effect = (
            lambda url, proxy=True, rewrite_fragments=True: url
        )
        return context

    @pytest.fixture
    def hooks(self, context):
        hooks = Hooks(
            {
                "config_noise": "noise",
                "h_embed_url": sentinel.h_embed_url,
                "ignore_prefixes": sentinel.prefixes,
                "rewrite": {"a_href": True},
            }
        )

        hooks.set_context(context)

        return hooks

    @pytest.fixture
    def Configuration(self):
        with patch("viahtml.hooks.hooks.Configuration", autospec=True) as Configuration:
            yield Configuration
