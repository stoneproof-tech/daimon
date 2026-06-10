# -*- coding: utf-8 -*-
"""Test del block explorer (Milestone 5).

Verifica che la catena d'esempio contenga gli eventi attesi (nascite, riproduzione,
fossili) e che tutte le pagine HTML si generino e mostrino genomi, genealogia,
fossili e royalty. Include uno smoke test del server HTTP via socket locale.
"""

import threading
import http.client

from daimon.explorer import (
    build_sample_chain, route,
    render_index, render_block, render_daimons, render_genealogy, render_fossils,
    serve, _make_handler,
)
from http.server import ThreadingHTTPServer


def test_sample_chain_ha_vita_completa():
    chain = build_sample_chain()
    ok, msg = chain.is_valid()
    assert ok, msg
    st = chain.tip_state
    assert len(st.daimons) >= 2          # almeno Pythia + figlio (o Mnemo)
    assert len(st.fossils) >= 1          # Hermes morto di inedia
    # Almeno un daimon di generazione 1 (riproduzione avvenuta).
    assert any(d["generation"] >= 1 for d in st.daimons.values())


def test_pagine_si_renderizzano():
    chain = build_sample_chain()
    idx = render_index(chain)
    assert "Panoramica" in idx and "supply" in idx
    dm = render_daimons(chain)
    assert "Daimon viventi" in dm and "royalty" in dm
    gen = render_genealogy(chain)
    assert "genealogic" in gen.lower()
    fos = render_fossils(chain)
    assert "Fossili" in fos
    blk = render_block(chain, 0)
    assert "Manifesto" in blk            # la genesi porta il manifesto
    # I genomi (motto) compaiono da qualche parte.
    assert "numero" in dm or "numero" in gen


def test_route_dispatch():
    chain = build_sample_chain()
    assert "Panoramica" in route(chain, "/", {})
    assert "Daimon" in route(chain, "/daimons", {})
    assert "404" in route(chain, "/inesistente", {})
    assert "Blocco #0" in route(chain, "/block", {"i": ["0"]})


def test_genealogia_mostra_fossile_e_generazioni():
    chain = build_sample_chain()
    gen = render_genealogy(chain)
    # Un fossile (Hermes) deve comparire marcato come tale.
    assert "fossile" in gen
    # Una stirpe con figlio: deve esserci un nodo gen1.
    assert "gen1" in gen


def test_http_smoke():
    chain = build_sample_chain()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(lambda: chain))
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/")
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        assert resp.status == 200
        assert "DAIMON" in body
        conn.request("GET", "/genealogy")
        assert conn.getresponse().status == 200
    finally:
        httpd.shutdown()
