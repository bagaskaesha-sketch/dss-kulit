"""
DSS Kebutuhan Bahan Kimia Pengolahan Kulit (versi Streamlit)
Database: Supabase Postgres. Deploy: Streamlit Community Cloud.

Secrets yang dibutuhkan:
  DEV_ID, DEV_PASS, USER_ID, USER_PASS, SUPABASE_URL, SUPABASE_KEY
"""
import hmac
import io
import os
import re

import pandas as pd
import streamlit as st
from supabase import create_client

TABEL = "formulasi"
KOLOM = ["id", "jenis_kulit", "tahapan", "senyawa", "persen", "satuan"]
# Faktor konversi dari kg: g dan mL (asumsi massa jenis 1 kg = 1 L) dikali 1000
SATUAN = {"kg": 1, "g": 1000, "mL": 1000, "L": 1}
BARU = "➕ Tambah baru..."

st.set_page_config(page_title="DSS Kimia Pengolahan Kulit", page_icon="🧪", layout="wide")


# ---------------------------------------------------------------------------
# Konfigurasi & database
# ---------------------------------------------------------------------------
def cfg(nama: str) -> str:
    """Baca dari st.secrets, fallback ke environment variable."""
    try:
        if nama in st.secrets:
            return str(st.secrets[nama])
    except Exception:  # noqa: BLE001
        pass
    return os.getenv(nama, "")


class DBError(Exception):
    """Error database dengan pesan ramah pengguna."""


@st.cache_resource
def db():
    url, key = cfg("SUPABASE_URL"), cfg("SUPABASE_KEY")
    if not url or not key:
        raise DBError("SUPABASE_URL / SUPABASE_KEY belum diisi di Secrets.")
    try:
        return create_client(url, key)
    except Exception as e:  # noqa: BLE001
        raise DBError(f"Gagal membuat koneksi ke Supabase: {str(e)[:200]}")


def jalankan(fn):
    try:
        return fn()
    except DBError:
        raise
    except Exception as e:  # noqa: BLE001
        teks = str(e)
        if "23505" in teks or "duplicate" in teks.lower():
            raise DBError("Data duplikat: kombinasi jenis kulit + tahapan + senyawa sudah ada.")
        if "satuan" in teks and ("column" in teks or "PGRST204" in teks):
            raise DBError("Kolom 'satuan' belum ada. Jalankan migrasi SQL di Supabase SQL Editor.")
        if "does not exist" in teks or "PGRST205" in teks:
            raise DBError("Tabel 'formulasi' belum ada. Jalankan setup.sql di Supabase SQL Editor.")
        raise DBError(f"Gagal mengakses database: {teks[:200]}")


def ambil_semua() -> pd.DataFrame:
    res = jalankan(
        lambda: db().table(TABEL).select("*").order("jenis_kulit").order("id").execute()
    )
    df = pd.DataFrame(res.data or [])
    if df.empty:
        return pd.DataFrame(columns=KOLOM)
    df["persen"] = df["persen"].astype(float)
    if "satuan" not in df:
        df["satuan"] = "kg"
    df["satuan"] = df["satuan"].fillna("kg")
    return df[KOLOM]


def rapikan(teks) -> str:
    return re.sub(r"\s+", " ", (teks or "").strip())


def flash(jenis: str, pesan: str):
    st.session_state["flash"] = (jenis, pesan)
    st.rerun()


def tampil_flash():
    if "flash" in st.session_state:
        jenis, pesan = st.session_state.pop("flash")
        getattr(st, jenis)(pesan)


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
def cocok(a: str, b: str, benar_a: str, benar_b: str) -> bool:
    if not benar_a or not benar_b:
        return False
    return (hmac.compare_digest(a.encode(), benar_a.encode())
            and hmac.compare_digest(b.encode(), benar_b.encode()))


def halaman_login():
    st.title("🧪 DSS Kebutuhan Bahan Kimia Pengolahan Kulit")
    with st.form("login"):
        uid = st.text_input("ID")
        pwd = st.text_input("Password", type="password")
        masuk = st.form_submit_button("Masuk", type="primary")
    if masuk:
        uid = uid.strip()
        if cocok(uid, pwd, cfg("DEV_ID"), cfg("DEV_PASS")):
            st.session_state["role"] = "dev"
            st.rerun()
        elif cocok(uid, pwd, cfg("USER_ID"), cfg("USER_PASS")):
            st.session_state["role"] = "user"
            st.rerun()
        else:
            st.error("❌ ID atau password salah.")


def logout_sidebar():
    with st.sidebar:
        st.write(f"Masuk sebagai: **{'Developer' if st.session_state['role'] == 'dev' else 'User'}**")
        if st.button("Logout"):
            st.session_state.clear()
            st.rerun()


# ---------------------------------------------------------------------------
# Interface Developer
# ---------------------------------------------------------------------------
def pilih_atau_baru(label: str, pilihan: list, kunci: str) -> str:
    """Selectbox dengan opsi tambah nilai baru."""
    terpilih = st.selectbox(label, pilihan + [BARU], key=f"sb_{kunci}")
    if terpilih == BARU:
        return st.text_input(f"{label} baru", key=f"tx_{kunci}")
    return terpilih


def halaman_developer():
    st.title("Developer: Kelola Formulasi")
    tampil_flash()
    try:
        df = ambil_semua()
    except DBError as e:
        st.error(f"❌ {e}")
        return

    jenis_list = sorted(df["jenis_kulit"].unique().tolist())
    tahap_list = list(dict.fromkeys(df["tahapan"].tolist()))

    st.subheader("Tambah formulasi")
    c1, c2 = st.columns(2)
    with c1:
        jenis = pilih_atau_baru("Jenis kulit", jenis_list, "jenis")
    with c2:
        tahapan = pilih_atau_baru("Tahapan", tahap_list, "tahap")
    c3, c4, c5 = st.columns([2, 2, 1])
    with c3:
        senyawa = st.text_input("Nama senyawa kimia", key="senyawa")
    with c4:
        persen = st.number_input("Persentase (% dari berat kulit)",
                                 min_value=0.0, value=None, format="%.4f", key="persen")
    with c5:
        satuan = st.selectbox("Satuan output", list(SATUAN), key="satuan")

    if st.button("➕ Tambah", type="primary"):
        jenis, tahapan = rapikan(jenis).title(), rapikan(tahapan).title()
        senyawa = rapikan(senyawa)
        if not (jenis and tahapan and senyawa):
            st.warning("⚠️ Jenis kulit, tahapan, dan senyawa wajib diisi.")
        elif persen is None or persen <= 0:
            st.warning("⚠️ Persentase harus angka lebih dari 0.")
        else:
            try:
                jalankan(lambda: db().table(TABEL).insert({
                    "jenis_kulit": jenis, "tahapan": tahapan,
                    "senyawa": senyawa, "persen": persen,
                    "satuan": satuan}).execute())
            except DBError as e:
                st.error(f"❌ {e}")
            else:
                flash("success", f"✅ Ditambahkan: {jenis} / {tahapan} / {senyawa} ({persen}%, output {satuan})")

    st.divider()
    st.subheader("Data formulasi (klik satu baris untuk edit / hapus)")
    if df.empty:
        st.info("Belum ada data.")
        return

    event = st.dataframe(df, hide_index=True, use_container_width=True,
                         on_select="rerun", selection_mode="single-row")
    baris = event.selection.rows
    if not baris:
        return

    row = df.iloc[baris[0]]
    st.write(f"Terpilih: **{row['jenis_kulit']} / {row['tahapan']} / {row['senyawa']}** "
             f"(ID {int(row['id'])}, {row['persen']}%)")
    ce1, ce2 = st.columns([2, 1])
    with ce1:
        persen_baru = st.number_input("Persentase baru (%)", min_value=0.0,
                                      value=float(row["persen"]), format="%.4f",
                                      key=f"persen_baru_{int(row['id'])}")
    with ce2:
        satuan_baru = st.selectbox("Satuan baru", list(SATUAN),
                                   index=list(SATUAN).index(row["satuan"]) if row["satuan"] in SATUAN else 0,
                                   key=f"satuan_baru_{int(row['id'])}")
    cu, ch = st.columns(2)
    if cu.button("✏️ Ubah persentase & satuan"):
        if persen_baru <= 0:
            st.warning("⚠️ Persentase harus angka lebih dari 0.")
        else:
            try:
                jalankan(lambda: db().table(TABEL).update({"persen": persen_baru, "satuan": satuan_baru})
                         .eq("id", int(row["id"])).execute())
            except DBError as e:
                st.error(f"❌ {e}")
            else:
                flash("success", f"✅ ID {int(row['id'])} diubah: {persen_baru}%, satuan {satuan_baru}")
    if ch.button("🗑️ Hapus baris"):
        try:
            jalankan(lambda: db().table(TABEL).delete().eq("id", int(row["id"])).execute())
        except DBError as e:
            st.error(f"❌ {e}")
        else:
            flash("success", f"🗑️ Baris ID {int(row['id'])} dihapus.")


# ---------------------------------------------------------------------------
# Interface User
# ---------------------------------------------------------------------------
def halaman_user():
    st.title("Hitung Kebutuhan Bahan Kimia")
    try:
        df = ambil_semua()
    except DBError as e:
        st.error(f"❌ {e}")
        return
    if df.empty:
        st.info("Belum ada formulasi. Hubungi developer.")
        return

    c1, c2, c3 = st.columns(3)
    with c1:
        jenis = st.selectbox("Jenis kulit", sorted(df["jenis_kulit"].unique().tolist()),
                             index=None, placeholder="Pilih jenis kulit")
    with c2:
        tahap_opsi = (list(dict.fromkeys(df[df["jenis_kulit"] == jenis]["tahapan"]))
                      if jenis else [])
        tahapan = st.selectbox("Tahapan", tahap_opsi, index=None,
                               placeholder="Pilih tahapan")
    with c3:
        berat = st.number_input("Berat kulit (kg)", min_value=0.0, value=None, format="%.3f")

    if not (jenis and tahapan):
        return
    if berat is None or berat <= 0:
        st.info("Masukkan berat kulit (kg) lebih dari 0.")
        return

    hasil = df[(df["jenis_kulit"] == jenis) & (df["tahapan"] == tahapan)].copy()
    # jumlah dasar (kg) lalu dikonversi ke satuan masing-masing senyawa
    hasil["jumlah"] = (hasil["persen"] / 100 * berat
                       * hasil["satuan"].map(SATUAN).fillna(1)).round(4)
    tampil = hasil[["senyawa", "persen", "jumlah", "satuan"]].rename(columns={
        "senyawa": "Senyawa", "persen": "Persen (%)", "jumlah": "Jumlah", "satuan": "Satuan"})
    st.dataframe(tampil, hide_index=True, use_container_width=True)
    per_satuan = hasil.groupby("satuan")["jumlah"].sum()
    ringkas = " + ".join(f"{v:,.4f} {k}" for k, v in per_satuan.items())
    st.markdown(f"**Total:** {ringkas} untuk {berat:g} kg kulit {jenis} ({tahapan})")
    st.caption("Satuan g dan mL dihitung dari kg dengan asumsi massa jenis 1 kg = 1 L.")

    # Export xlsx
    out = pd.DataFrame({
        "Jenis Kulit": jenis, "Tahapan": tahapan, "Berat Kulit (kg)": berat,
        "Senyawa": hasil["senyawa"].values, "Persen (%)": hasil["persen"].values,
        "Jumlah": hasil["jumlah"].values, "Satuan": hasil["satuan"].values})
    baris_total = pd.DataFrame([{
        "Jenis Kulit": jenis, "Tahapan": tahapan, "Berat Kulit (kg)": berat,
        "Senyawa": "TOTAL", "Persen (%)": None, "Jumlah": None, "Satuan": ringkas}])
    out = pd.concat([out, baris_total], ignore_index=True)
    buf = io.BytesIO()
    out.to_excel(buf, index=False, engine="openpyxl")
    nama = re.sub(r"[^A-Za-z0-9_-]+", "_", f"{jenis}_{tahapan}")
    st.download_button("📥 Export ke Excel (.xlsx)", buf.getvalue(),
                       file_name=f"kebutuhan_kimia_{nama}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
role = st.session_state.get("role")
if role is None:
    halaman_login()
else:
    logout_sidebar()
    if role == "dev":
        halaman_developer()
    else:
        halaman_user()
