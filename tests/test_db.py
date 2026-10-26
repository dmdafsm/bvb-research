import duckdb

from bvb import db


def test_publish_snapshot_includes_uncheckpointed_writes(tmp_path):
    src, dst = tmp_path / "w.duckdb", tmp_path / "r.duckdb"
    con = db.connect(src)
    con.execute("INSERT INTO watchlist (symbol) VALUES ('TLV')")
    db.publish_snapshot(con, src, dst)

    reader = duckdb.connect(str(dst), read_only=True)  # in timp ce scriitorul e inca deschis
    assert reader.execute("SELECT symbol FROM watchlist").fetchall() == [("TLV",)]

    con.execute("INSERT INTO watchlist (symbol) VALUES ('SNP')")
    db.publish_snapshot(con, src, dst)
    # cititorul deschis pastreaza copia veche; dupa inchidere, o conexiune noua vede copia noua
    assert reader.execute("SELECT count(*) FROM watchlist").fetchone()[0] == 1
    reader.close()
    fresh = duckdb.connect(str(dst), read_only=True)
    assert fresh.execute("SELECT count(*) FROM watchlist").fetchone()[0] == 2
    assert not (tmp_path / "r.duckdb.tmp").exists()


def test_connect_registers_publishing_only_for_main_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_writer", None)
    db.connect(tmp_path / "other.duckdb")
    assert db._writer is None
