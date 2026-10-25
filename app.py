"""
DSS Kebutuhan Bahan Kimia Pengolahan Kulit
Gradio (Blocks) + Supabase Postgres. Siap deploy di Hugging Face Spaces.

Secrets / environment variable yang dibutuhkan:
  DEV_ID, DEV_PASS, USER_ID, USER_PASS, SUPABASE_URL, SUPABASE_KEY
"""
import hmac
import os
import re
import tempfile

import gradio as gr
import pandas as pd
from supabase import create_client

TABEL = "formulasi"
KOLOM = ["id", "jenis_kulit", "tahapan", "senyawa", "persen"]

# Kredensial login dibaca dari secrets (tidak ada yang hardcode)
DEV_ID = os.getenv("DEV_ID", "")
DEV_PASS = os.getenv("DEV_PASS", "")
USER_ID = os.getenv("USER_ID", "")
USER_PASS = os.getenv("USER_PASS", "")


# ---------------------------------------------------------------------------
# Database (Supabase)
# ---------------------------------------------------------------------------
class DBError(Exception):
    """Error database dengan pesan yang ramah dibaca pengguna."""


_client = None


def db():
    """Buat koneksi Supabase sekali saja (lazy)."""
    global _client
    if _client is None:
        url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY")
        if not url or not key:
            raise DBError("SUPABASE_URL / SUPABASE_KEY belum diisi di Secrets.")
        try:
            _client = create_client(url, key)
        except Exception as e:  # noqa: BLE001
            raise DBError(f"Gagal membuat koneksi ke Supabase: {str(e)[:200]}")
    return _client


def jalankan(fn):
    """Jalankan query dan terjemahkan error jadi pesan jelas."""
    try:
        return fn()
    except DBError:
        raise
    except Exception as e:  # noqa: BLE001
        teks = str(e)
        if "23505" in teks or "duplicate" in teks.lower():
            raise DBError("Data duplikat: kombinasi jenis kulit + tahapan + senyawa sudah ada.")
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
    return df[KOLOM]


def rapikan(teks) -> str:
    return re.sub(r"\s+", " ", (teks or "").strip())


def daftar_pilihan(df: pd.DataFrame):
    jenis = sorted(df["jenis_kulit"].unique().tolist())
    tahapan = list(dict.fromkeys(df["tahapan"].tolist()))  # urut sesuai input
    return jenis, tahapan


# ---------------------------------------------------------------------------
# Login / logout
# ---------------------------------------------------------------------------
def cocok(a: str, b: str, benar_a: str, benar_b: str) -> bool:
    if not benar_a or not benar_b:  # secrets belum diisi -> tolak
        return False
    ok_id = hmac.compare_digest(a.encode(), benar_a.encode())
    ok_pw = hmac.compare_digest(b.encode(), benar_b.encode())
    return ok_id and ok_pw


def segarkan_dev():
    df = ambil_semua()
    jenis, tahapan = daftar_pilihan(df)
    return df, gr.update(choices=jenis), gr.update(choices=tahapan)


def login(uid, pwd):
    uid, pwd = (uid or "").strip(), pwd or ""
    skip = gr.update()
    if cocok(uid, pwd, DEV_ID, DEV_PASS):
        role = "dev"
    elif cocok(uid, pwd, USER_ID, USER_PASS):
        role = "user"
    else:
        return (None, gr.update(visible=True), gr.update(visible=False),
                gr.update(visible=False), "❌ ID atau password salah.",
                skip, skip, skip, skip)

    df_dev, dd_jenis_dev, dd_tahap_dev = skip, skip, skip
    dd_jenis_user = skip
    try:
        df = ambil_semua()
        jenis, tahapan = daftar_pilihan(df)
        df_dev = df
        dd_jenis_dev = gr.update(choices=jenis)
        dd_tahap_dev = gr.update(choices=tahapan)
        dd_jenis_user = gr.update(choices=jenis, value=None)
    except DBError as e:
        gr.Warning(str(e))

    return (role, gr.update(visible=False),
            gr.update(visible=role == "dev"), gr.update(visible=role == "user"),
            "", df_dev, dd_jenis_dev, dd_tahap_dev, dd_jenis_user)


def logout():
    return (None, gr.update(visible=True), gr.update(visible=False),
            gr.update(visible=False), "", "")


# ---------------------------------------------------------------------------
# Interface Developer
# ---------------------------------------------------------------------------
TOLAK = ("⛔ Akses ditolak.", gr.update(), gr.update(), gr.update())


def dev_tambah(role, jenis, tahapan, senyawa, persen):
    if role != "dev":
        return TOLAK
    jenis, tahapan = rapikan(jenis).title(), rapikan(tahapan).title()
    senyawa = rapikan(senyawa)
    if not (jenis and tahapan and senyawa):
        return ("⚠️ Jenis kulit, tahapan, dan senyawa wajib diisi.",
                gr.update(), gr.update(), gr.update())
    if persen is None or persen <= 0:
        return ("⚠️ Persentase harus angka lebih dari 0.",
                gr.update(), gr.update(), gr.update())
    try:
        jalankan(lambda: db().table(TABEL).insert({
            "jenis_kulit": jenis, "tahapan": tahapan,
            "senyawa": senyawa, "persen": persen}).execute())
        df, dd_j, dd_t = segarkan_dev()
    except DBError as e:
        return (f"❌ {e}", gr.update(), gr.update(), gr.update())
    return (f"✅ Ditambahkan: {jenis} / {tahapan} / {senyawa} ({persen}%)", df, dd_j, dd_t)


def dev_pilih_baris(df, evt: gr.SelectData):
    baris = df.iloc[evt.index[0]]
    info = f"Terpilih: {baris['jenis_kulit']} / {baris['tahapan']} / {baris['senyawa']}"
    return int(baris["id"]), float(baris["persen"]), info


def dev_ubah(role, id_sel, persen_baru):
    if role != "dev":
        return TOLAK
    if id_sel is None:
        return ("⚠️ Klik dulu satu baris di tabel.", gr.update(), gr.update(), gr.update())
    if persen_baru is None or persen_baru <= 0:
        return ("⚠️ Persentase harus angka lebih dari 0.",
                gr.update(), gr.update(), gr.update())
    try:
        jalankan(lambda: db().table(TABEL).update({"persen": persen_baru})
                 .eq("id", int(id_sel)).execute())
        df, dd_j, dd_t = segarkan_dev()
    except DBError as e:
        return (f"❌ {e}", gr.update(), gr.update(), gr.update())
    return (f"✅ Persentase baris ID {int(id_sel)} diubah jadi {persen_baru}%", df, dd_j, dd_t)


def dev_hapus(role, id_sel):
    if role != "dev":
        return TOLAK
    if id_sel is None:
        return ("⚠️ Klik dulu satu baris di tabel.", gr.update(), gr.update(), gr.update())
    try:
        jalankan(lambda: db().table(TABEL).delete().eq("id", int(id_sel)).execute())
        df, dd_j, dd_t = segarkan_dev()
    except DBError as e:
        return (f"❌ {e}", gr.update(), gr.update(), gr.update())
    return (f"🗑️ Baris ID {int(id_sel)} dihapus.", df, dd_j, dd_t)


def dev_muat_ulang(role):
    if role != "dev":
        return TOLAK
    try:
        df, dd_j, dd_t = segarkan_dev()
    except DBError as e:
        return (f"❌ {e}", gr.update(), gr.update(), gr.update())
    return ("🔄 Data dimuat ulang.", df, dd_j, dd_t)


# ---------------------------------------------------------------------------
# Interface User
# ---------------------------------------------------------------------------
def user_muat(role):
    if role != "user":
        return gr.update(), gr.update()
    try:
        jenis, _ = daftar_pilihan(ambil_semua())
    except DBError as e:
        gr.Warning(str(e))
        return gr.update(), gr.update()
    return gr.update(choices=jenis, value=None), gr.update(choices=[], value=None)


def user_ganti_jenis(jenis):
    if not jenis:
        return gr.update(choices=[], value=None)
    try:
        df = ambil_semua()
    except DBError as e:
        gr.Warning(str(e))
        return gr.update()
    tahapan = list(dict.fromkeys(df[df["jenis_kulit"] == jenis]["tahapan"]))
    return gr.update(choices=tahapan, value=None)


def hitung_df(jenis, tahapan, berat) -> pd.DataFrame:
    df = ambil_semua()
    df = df[(df["jenis_kulit"] == jenis) & (df["tahapan"] == tahapan)].copy()
    df["berat_kg"] = (df["persen"] / 100 * berat).round(4)
    return df[["senyawa", "persen", "berat_kg"]]


def cek_input(role, jenis, tahapan, berat):
    if role != "user":
        return "⛔ Akses ditolak."
    if not jenis or not tahapan:
        return "⚠️ Pilih jenis kulit dan tahapan dulu."
    if berat is None or berat <= 0:
        return "⚠️ Berat kulit harus lebih dari 0 kg."
    return None


def user_hitung(role, jenis, tahapan, berat):
    salah = cek_input(role, jenis, tahapan, berat)
    kosong = pd.DataFrame(columns=["Senyawa", "Persen (%)", "Berat (kg)"])
    if salah:
        return kosong, salah
    try:
        df = hitung_df(jenis, tahapan, berat)
    except DBError as e:
        return kosong, f"❌ {e}"
    if df.empty:
        return kosong, "⚠️ Belum ada formulasi untuk kombinasi ini."
    df.columns = ["Senyawa", "Persen (%)", "Berat (kg)"]
    total = df["Berat (kg)"].sum()
    return df, f"**Total bahan kimia: {total:,.4f} kg** untuk {berat:g} kg kulit {jenis} ({tahapan})"


def user_export(role, jenis, tahapan, berat):
    salah = cek_input(role, jenis, tahapan, berat)
    if salah:
        gr.Warning(salah)
        return None
    try:
        df = hitung_df(jenis, tahapan, berat)
    except DBError as e:
        gr.Warning(str(e))
        return None
    if df.empty:
        gr.Warning("Belum ada formulasi untuk kombinasi ini.")
        return None
    out = pd.DataFrame({
        "Jenis Kulit": jenis,
        "Tahapan": tahapan,
        "Berat Kulit (kg)": berat,
        "Senyawa": df["senyawa"].values,
        "Persen (%)": df["persen"].values,
        "Berat Senyawa (kg)": df["berat_kg"].values,
    })
    total = pd.DataFrame([{
        "Jenis Kulit": jenis, "Tahapan": tahapan, "Berat Kulit (kg)": berat,
        "Senyawa": "TOTAL", "Persen (%)": out["Persen (%)"].sum(),
        "Berat Senyawa (kg)": out["Berat Senyawa (kg)"].sum()}])
    out = pd.concat([out, total], ignore_index=True)

    aman = re.sub(r"[^A-Za-z0-9_-]+", "_", f"{jenis}_{tahapan}")
    path = os.path.join(tempfile.mkdtemp(), f"kebutuhan_kimia_{aman}.xlsx")
    out.to_excel(path, index=False, engine="openpyxl")
    return path


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
with gr.Blocks(title="DSS Kimia Pengolahan Kulit") as demo:
    role_state = gr.State(None)  # None | "dev" | "user" (disimpan di server)

    gr.Markdown("# 🧪 DSS Kebutuhan Bahan Kimia Pengolahan Kulit")

    # ---- Halaman login ----
    with gr.Column(visible=True) as col_login:
        in_id = gr.Textbox(label="ID")
        in_pw = gr.Textbox(label="Password", type="password")
        btn_login = gr.Button("Masuk", variant="primary")
        msg_login = gr.Markdown()

    # ---- Interface Developer ----
    with gr.Column(visible=False) as col_dev:
        with gr.Row():
            gr.Markdown("## Developer: Kelola Formulasi")
            btn_logout_dev = gr.Button("Logout", scale=0)
        with gr.Row():
            dev_jenis = gr.Dropdown(label="Jenis kulit (ketik untuk tambah baru)",
                                    choices=[], allow_custom_value=True)
            dev_tahap = gr.Dropdown(label="Tahapan (ketik untuk tambah baru)",
                                    choices=[], allow_custom_value=True)
        with gr.Row():
            dev_senyawa = gr.Textbox(label="Nama senyawa kimia")
            dev_persen = gr.Number(label="Persentase (% dari berat kulit)", value=None)
        btn_tambah = gr.Button("➕ Tambah", variant="primary")
        dev_status = gr.Markdown()

        gr.Markdown("### Data formulasi (klik baris untuk edit / hapus)")
        dev_tabel = gr.Dataframe(
            value=pd.DataFrame(columns=KOLOM), interactive=False, wrap=True)
        with gr.Row():
            dev_id_sel = gr.Number(label="ID terpilih", interactive=False, precision=0)
            dev_persen_baru = gr.Number(label="Persentase baru (%)")
        dev_info = gr.Markdown()
        with gr.Row():
            btn_ubah = gr.Button("✏️ Ubah persentase")
            btn_hapus = gr.Button("🗑️ Hapus baris", variant="stop")
            btn_muat_dev = gr.Button("🔄 Muat ulang")

    # ---- Interface User ----
    with gr.Column(visible=False) as col_user:
        with gr.Row():
            gr.Markdown("## Hitung Kebutuhan Bahan Kimia")
            btn_logout_user = gr.Button("Logout", scale=0)
        with gr.Row():
            u_jenis = gr.Dropdown(label="Jenis kulit", choices=[])
            u_tahap = gr.Dropdown(label="Tahapan", choices=[])
            u_berat = gr.Number(label="Berat kulit (kg)", value=None)
        with gr.Row():
            btn_hitung = gr.Button("Hitung", variant="primary")
            btn_muat_user = gr.Button("🔄 Muat ulang pilihan")
        u_tabel = gr.Dataframe(
            value=pd.DataFrame(columns=["Senyawa", "Persen (%)", "Berat (kg)"]),
            interactive=False, wrap=True)
        u_total = gr.Markdown()
        btn_export = gr.Button("📥 Export ke Excel (.xlsx)")
        u_file = gr.File(label="File hasil", interactive=False)

    # ---- Event wiring ----
    btn_login.click(
        login, [in_id, in_pw],
        [role_state, col_login, col_dev, col_user, msg_login,
         dev_tabel, dev_jenis, dev_tahap, u_jenis])
    in_pw.submit(
        login, [in_id, in_pw],
        [role_state, col_login, col_dev, col_user, msg_login,
         dev_tabel, dev_jenis, dev_tahap, u_jenis])

    for tombol in (btn_logout_dev, btn_logout_user):
        tombol.click(logout, None,
                     [role_state, col_login, col_dev, col_user, msg_login, in_pw])

    dev_out = [dev_status, dev_tabel, dev_jenis, dev_tahap]
    btn_tambah.click(dev_tambah,
                     [role_state, dev_jenis, dev_tahap, dev_senyawa, dev_persen], dev_out)
    dev_tabel.select(dev_pilih_baris, dev_tabel, [dev_id_sel, dev_persen_baru, dev_info])
    btn_ubah.click(dev_ubah, [role_state, dev_id_sel, dev_persen_baru], dev_out)
    btn_hapus.click(dev_hapus, [role_state, dev_id_sel], dev_out)
    btn_muat_dev.click(dev_muat_ulang, role_state, dev_out)

    u_jenis.change(user_ganti_jenis, u_jenis, u_tahap)
    btn_muat_user.click(user_muat, role_state, [u_jenis, u_tahap])
    btn_hitung.click(user_hitung, [role_state, u_jenis, u_tahap, u_berat],
                     [u_tabel, u_total])
    btn_export.click(user_export, [role_state, u_jenis, u_tahap, u_berat], u_file)

if __name__ == "__main__":
    demo.launch()
