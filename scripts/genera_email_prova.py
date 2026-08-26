"""Crea messaggi .eml di prova nella cartella della posta.

Serve a collaudare il motore di acquisizione della sessione 10 **senza nessun
accesso alla casella aziendale**. Scrive nella cartella MAIL_LOCAL_PATH una
ventina di file `.eml` che esercitano tutti i rami dell'attribuzione, compresi
quelli che nessuno si ricorderebbe di provare a mano.

    .venv\\Scripts\\activate
    python scripts/genera_email_prova.py

Poi si apre <http://localhost:8000/posta> e si preme "Elabora la posta".


PERCHE' I MESSAGGI SONO SEMPRE GLI STESSI
-----------------------------------------

**Gli identificativi non sono casuali.** Rieseguendo questo script si
riscrivono gli stessi venti file, con gli stessi `Message-ID`: eseguire la
generazione e l'elaborazione due volte di fila deve produrre lo stesso numero
di messaggi archiviati e **nessun doppione**. E' il secondo criterio di
accettazione della sessione, e con identificativi casuali non si potrebbe
verificare - ogni giro sembrerebbe funzionare.

Per la stessa ragione le date sono calcolate all'indietro a partire da oggi:
restano realistiche senza dover cambiare lo script ogni mese.

**I codici prodotto invece si leggono dal database.** Un messaggio che parla di
un prodotto che in Aurora non esiste finirebbe sempre in quarantena, e i rami
"riconosciuto" non si proverebbero mai. Lo script cerca due prodotti veri; se
non ne trova, lo dice e si ferma invece di scrivere venti file inutili.


CHE COSA SI OTTIENE
-------------------

I venti messaggi coprono, nell'ordine, tutti e quattro i rami:

  a. oggetto formattato `[CODICE][Vn][MOTIVO]`, anche con `R:`, `Re:`,
     `Fwd:`, `I:` davanti e con spazi in mezzo alle parentesi;
  b. codice prodotto scritto in mezzo alla frase, senza parentesi;
  c. risposte che ereditano l'attribuzione dal messaggio a cui rispondono;
  d. messaggi senza nessun riferimento, che vanno in quarantena.

Piu' i casi che rompono le cose: allegati grandi, lettere accentate, corpo in
solo HTML, versione inesistente, file malformato, messaggio senza Message-ID.
"""

import sys
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import format_datetime
from pathlib import Path

# Lo script si esegue dalla radice del progetto: senza questa riga
# "import app" non funzionerebbe, perche' scripts/ non e' nel percorso.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Product, ProductVersion  # noqa: E402

# Il dominio degli identificativi inventati. Non e' un dominio vero: serve a
# rendere evidente, guardando il database, che questi messaggi vengono da una
# generazione di prova e non da una casella.
DOMINIO = "prova.aurora.local"

# I due interlocutori dei messaggi finti.
CLIENTE = "mario.rossi@cliente-di-prova.it"
NOSTRO = "ufficio.tecnico@azienda-di-prova.it"
COLLEGA = "anna.verdi@azienda-di-prova.it"

# Quanto pesa l'allegato "grande". Tre megabyte: abbastanza da vedere la
# differenza nell'elenco degli allegati e da esercitare la scrittura a blocchi
# dell'archivio, abbastanza poco da non riempire il disco a ogni prova.
ALLEGATO_GRANDE_MB = 3


def _quando(giorni_fa: int, ora: int = 9) -> datetime:
    """Una data realistica, calcolata all'indietro a partire da oggi."""
    momento = datetime.now(timezone.utc) - timedelta(days=giorni_fa)
    return momento.replace(hour=ora, minute=0, second=0, microsecond=0)


def _identificativo(nome: str) -> str:
    """Il Message-ID di un messaggio di prova. **Stabile fra un giro e l'altro.**"""
    return f"<prova-{nome}@{DOMINIO}>"


def _messaggio(
    *,
    nome: str,
    da: str,
    a: str,
    oggetto: str | None,
    corpo: str,
    giorni_fa: int,
    copia: str | None = None,
    in_risposta_a: str | None = None,
    riferimenti: list[str] | None = None,
    html: str | None = None,
    allegati: list[tuple[str, str, bytes]] | None = None,
    con_identificativo: bool = True,
) -> EmailMessage:
    """Costruisce un messaggio con la libreria standard.

    Si usa `email.message.EmailMessage` e non si scrivono i byte a mano di
    proposito: cosi' i file di prova sono messaggi veri, con le intestazioni
    codificate come le codifica un programma di posta - lettere accentate
    comprese - e non un'imitazione che funziona solo con il nostro lettore.
    """
    messaggio = EmailMessage()

    if con_identificativo:
        messaggio["Message-ID"] = _identificativo(nome)

    messaggio["From"] = da
    messaggio["To"] = a
    if copia:
        messaggio["Cc"] = copia
    if oggetto is not None:
        messaggio["Subject"] = oggetto
    messaggio["Date"] = format_datetime(_quando(giorni_fa))

    if in_risposta_a:
        messaggio["In-Reply-To"] = in_risposta_a
    if riferimenti:
        messaggio["References"] = " ".join(riferimenti)

    messaggio.set_content(corpo)

    if html is not None:
        messaggio.add_alternative(html, subtype="html")

    for nome_file, tipo, contenuto in allegati or []:
        principale, _, secondario = tipo.partition("/")
        messaggio.add_attachment(
            contenuto,
            maintype=principale,
            subtype=secondario,
            filename=nome_file,
        )

    return messaggio


def _prodotti_di_prova() -> list[tuple[str, int]]:
    """Due prodotti veri del database, con il numero della loro ultima versione.

    Restituisce un elenco di coppie (codice, numero di versione piu' alto).
    Senza prodotti veri i rami "riconosciuto" non si proverebbero: e' il motivo
    per cui questo script legge il database invece di inventarsi dei codici.
    """
    with SessionLocal() as db:
        prodotti = db.scalars(
            select(Product)
            .where(Product.is_active.is_(True))
            .order_by(Product.created_at)
            .limit(2)
        ).all()

        trovati: list[tuple[str, int]] = []
        for prodotto in prodotti:
            ultima = db.scalar(
                select(ProductVersion.version_number)
                .where(ProductVersion.product_id == prodotto.id)
                .order_by(ProductVersion.version_number.desc())
                .limit(1)
            )
            if ultima is not None:
                trovati.append((prodotto.code, int(ultima)))

    return trovati


def _corpo(righe: list[str]) -> str:
    """Un corpo di messaggio plausibile, con saluti e firma."""
    return "\n".join(["Buongiorno,", "", *righe, "", "Cordiali saluti"])


def costruisci(prodotti: list[tuple[str, int]]) -> list[tuple[str, EmailMessage]]:
    """I messaggi di prova, come coppie (nome del file, messaggio).

    L'ordine dei file conta: la cartella si legge in ordine di nome, e la
    numerazione in testa serve a far arrivare le risposte **dopo** i messaggi
    a cui rispondono. Non e' obbligatorio - il motore ricostruisce il filo
    anche al contrario - ma cosi' il collaudo somiglia alla realta'.
    """
    codice_uno, versione_uno = prodotti[0]
    codice_due, versione_due = prodotti[1] if len(prodotti) > 1 else prodotti[0]

    messaggi: list[tuple[str, EmailMessage]] = []

    def aggiungi(numero: int, nome: str, messaggio: EmailMessage) -> None:
        messaggi.append((f"{numero:02d}-{nome}.eml", messaggio))

    # --- (a) l'oggetto formattato, in tutte le sue storture ----------------

    aggiungi(1, "formato-pieno", _messaggio(
        nome="formato-pieno",
        da=CLIENTE, a=NOSTRO,
        oggetto=f"[{codice_uno}][V{versione_uno}][SPECS] Tensione di ingresso",
        corpo=_corpo(["confermiamo la tensione di ingresso a 24 V."]),
        giorni_fa=20,
    ))

    aggiungi(2, "formato-senza-versione", _messaggio(
        nome="formato-senza-versione",
        da=CLIENTE, a=NOSTRO,
        oggetto=f"[{codice_uno}][RFQ] Richiesta di offerta",
        corpo=_corpo(["vi chiediamo un'offerta per venti pezzi."]),
        giorni_fa=19,
    ))

    aggiungi(3, "formato-con-spazi", _messaggio(
        nome="formato-con-spazi",
        da=NOSTRO, a=CLIENTE, copia=COLLEGA,
        oggetto=f"[ {codice_uno} ][ v{versione_uno} ][ quote ] Offerta 2026-114",
        corpo=_corpo(["in allegato l'offerta richiesta."]),
        giorni_fa=18,
        allegati=[("offerta-2026-114.txt", "text/plain",
                   b"Offerta di prova. Venti pezzi, consegna otto settimane.")],
    ))

    aggiungi(4, "formato-con-erre", _messaggio(
        nome="formato-con-erre",
        da=CLIENTE, a=NOSTRO,
        oggetto=f"R: [{codice_uno}][V{versione_uno}][QUOTE] Offerta 2026-114",
        corpo=_corpo(["l'offerta va bene, procedete pure."]),
        giorni_fa=17,
    ))

    aggiungi(5, "formato-con-re-fwd", _messaggio(
        nome="formato-con-re-fwd",
        da=COLLEGA, a=NOSTRO,
        oggetto=f"Re: Fwd:  R:  [{codice_uno}][V{versione_uno}][DESIGN] Schema",
        corpo=_corpo(["giro a te lo scambio con il cliente sullo schema."]),
        giorni_fa=16,
    ))

    aggiungi(6, "formato-inoltro-italiano", _messaggio(
        nome="formato-inoltro-italiano",
        da=COLLEGA, a=NOSTRO,
        oggetto=f"I: [{codice_due}][V{versione_due}][TEST] Esito delle prove",
        corpo=_corpo(["le prove di tipo sono andate a buon fine."]),
        giorni_fa=15,
    ))

    aggiungi(7, "formato-motivo-sconosciuto", _messaggio(
        nome="formato-motivo-sconosciuto",
        da=CLIENTE, a=NOSTRO,
        oggetto=f"[{codice_due}][V{versione_due}][GARANZIA] Estensione",
        corpo=_corpo([
            "chiediamo l'estensione della garanzia a trentasei mesi.",
            "",
            "Il motivo GARANZIA non e' fra quelli ammessi: il messaggio deve",
            "essere attribuito lo stesso, e il motivo risultare non",
            "riconosciuto nella sua scheda.",
        ]),
        giorni_fa=14,
    ))

    # --- Le lettere accentate e il corpo in solo HTML ----------------------

    aggiungi(8, "accenti", _messaggio(
        nome="accenti",
        da=CLIENTE, a=NOSTRO,
        oggetto=f"[{codice_uno}][V{versione_uno}][CHANGE] Modifica già concordata",
        corpo=_corpo([
            "come da accordi: la tensione è 48 V e non 24 V.",
            "L'unità va sostituita entro martedì; l'attività è già pianificata.",
            "Perché sia chiaro: nessun'altra caratteristica cambia.",
        ]),
        giorni_fa=13,
        allegati=[("relazione-tecnica-più-recente.txt", "text/plain",
                   "Relazione con accenti: perché, però, città.".encode("utf-8"))],
    ))

    aggiungi(9, "solo-html", _messaggio(
        nome="solo-html",
        da=CLIENTE, a=NOSTRO,
        oggetto=f"[{codice_uno}][V{versione_uno}][DELIVERY] Date di consegna",
        corpo="Se leggi questo, il messaggio e' stato letto come testo.",
        html=(
            "<html><head><style>p { color: red; }</style></head><body>"
            "<p>Buongiorno,</p>"
            "<p>le date di consegna sono <b>confermate</b>:</p>"
            "<table><tr><td>Prima tranche</td><td>15 settembre</td></tr>"
            "<tr><td>Seconda tranche</td><td>30 ottobre</td></tr></table>"
            "<p>Cordiali saluti</p>"
            "<script>document.write('questo non si deve leggere');</script>"
            "</body></html>"
        ),
        giorni_fa=12,
    ))

    aggiungi(10, "allegato-grande", _messaggio(
        nome="allegato-grande",
        da=CLIENTE, a=NOSTRO,
        oggetto=f"[{codice_uno}][V{versione_uno}][DESIGN] Disegni meccanici",
        corpo=_corpo(["in allegato i disegni meccanici aggiornati."]),
        giorni_fa=11,
        allegati=[
            ("disegni-meccanici.bin", "application/octet-stream",
             b"A" * (ALLEGATO_GRANDE_MB * 1024 * 1024)),
            ("nota-di-accompagnamento.txt", "text/plain",
             b"Due allegati nello stesso messaggio, di dimensioni diverse."),
        ],
    ))

    # --- (b) il codice in mezzo alla frase, senza parentesi ----------------

    aggiungi(11, "codice-libero", _messaggio(
        nome="codice-libero",
        da=CLIENTE, a=NOSTRO,
        oggetto=f"Domanda sul {codice_uno} - alimentazione",
        corpo=_corpo(["il codice sta nell'oggetto ma senza parentesi."]),
        giorni_fa=10,
    ))

    aggiungi(12, "codice-libero-punteggiatura", _messaggio(
        nome="codice-libero-punteggiatura",
        da=CLIENTE, a=NOSTRO,
        oggetto=f"Ordine di ricambi (prodotto: {codice_due}), urgente",
        corpo=_corpo(["qui il codice e' fra parentesi tonde e seguito da virgola."]),
        giorni_fa=9,
    ))

    # --- (c) il filo di conversazione --------------------------------------
    #
    # Il capostipite ha il codice nell'oggetto; le due risposte no, e devono
    # ereditare l'attribuzione dagli header In-Reply-To e References.

    capostipite = _identificativo("filo-1-inizio")
    risposta = _identificativo("filo-2-risposta")

    aggiungi(13, "filo-1-inizio", _messaggio(
        nome="filo-1-inizio",
        da=CLIENTE, a=NOSTRO,
        oggetto=f"[{codice_due}][V{versione_due}][SPECS] Requisiti di prova",
        corpo=_corpo(["apriamo qui la discussione sui requisiti di prova."]),
        giorni_fa=8,
    ))

    aggiungi(14, "filo-2-risposta", _messaggio(
        nome="filo-2-risposta",
        da=NOSTRO, a=CLIENTE,
        oggetto="Re: Requisiti di prova",
        corpo=_corpo([
            "rispondo senza il codice nell'oggetto: l'attribuzione deve",
            "arrivare dall'intestazione In-Reply-To.",
        ]),
        giorni_fa=7,
        in_risposta_a=capostipite,
        riferimenti=[capostipite],
    ))

    aggiungi(15, "filo-3-controrisposta", _messaggio(
        nome="filo-3-controrisposta",
        da=CLIENTE, a=NOSTRO, copia=COLLEGA,
        oggetto="Re: Re: Requisiti di prova",
        corpo=_corpo([
            "terza mail della stessa conversazione, sempre senza codice.",
        ]),
        giorni_fa=6,
        in_risposta_a=risposta,
        riferimenti=[capostipite, risposta],
    ))

    # --- (d) la quarantena, nelle sue varieta' ------------------------------

    aggiungi(16, "quarantena-senza-codice", _messaggio(
        nome="quarantena-senza-codice",
        da=CLIENTE, a=NOSTRO,
        oggetto="Richiesta di informazioni generali",
        corpo=_corpo([
            "nessun codice, nessuna conversazione: va in quarantena.",
        ]),
        giorni_fa=5,
    ))

    aggiungi(17, "quarantena-prodotto-inesistente", _messaggio(
        nome="quarantena-prodotto-inesistente",
        da=CLIENTE, a=NOSTRO,
        oggetto="[ZZZ9999-00-000XX][V1][SPECS] Prodotto che non esiste",
        corpo=_corpo([
            "l'oggetto e' formattato benissimo ma quel prodotto in Aurora",
            "non c'e': quarantena.",
        ]),
        giorni_fa=4,
    ))

    aggiungi(18, "quarantena-versione-inesistente", _messaggio(
        nome="quarantena-versione-inesistente",
        da=CLIENTE, a=NOSTRO,
        oggetto=f"[{codice_uno}][V99][CHANGE] Versione che non esiste",
        corpo=_corpo([
            "il prodotto c'e', la versione 99 no. Aurora non ne sceglie",
            "un'altra al posto nostro: quarantena, con scritto perche'.",
        ]),
        giorni_fa=3,
    ))

    # Un filo intero in quarantena: serve a provare l'assegnazione a mano che
    # si propaga a tutta la conversazione (terzo criterio di accettazione).
    orfano = _identificativo("quarantena-filo-1")

    aggiungi(19, "quarantena-filo-1", _messaggio(
        nome="quarantena-filo-1",
        da=CLIENTE, a=NOSTRO,
        oggetto="Convocazione riunione di avanzamento",
        corpo=_corpo(["nessun codice: questo filo va assegnato a mano."]),
        giorni_fa=2,
    ))

    aggiungi(20, "quarantena-filo-2", _messaggio(
        nome="quarantena-filo-2",
        da=NOSTRO, a=CLIENTE,
        oggetto="Re: Convocazione riunione di avanzamento",
        corpo=_corpo(["seconda mail dello stesso filo, sempre senza codice."]),
        giorni_fa=2,
        in_risposta_a=orfano,
        riferimenti=[orfano],
    ))

    aggiungi(21, "quarantena-filo-3", _messaggio(
        nome="quarantena-filo-3",
        da=COLLEGA, a=CLIENTE,
        oggetto="Re: Re: Convocazione riunione di avanzamento",
        corpo=_corpo(["terza mail dello stesso filo."]),
        giorni_fa=1,
        in_risposta_a=orfano,
        riferimenti=[orfano],
    ))

    # --- I casi che rompono le cose ----------------------------------------

    aggiungi(22, "senza-message-id", _messaggio(
        nome="senza-message-id",
        da=CLIENTE, a=NOSTRO,
        oggetto=f"[{codice_uno}][V{versione_uno}][ADMIN] Fattura 2026/451",
        corpo=_corpo([
            "questo messaggio non dichiara nessun Message-ID: Aurora deve",
            "costruirgliene uno dall'impronta del file, e non archiviarlo",
            "due volte alla seconda elaborazione.",
        ]),
        giorni_fa=1,
        con_identificativo=False,
    ))

    aggiungi(23, "senza-oggetto", _messaggio(
        nome="senza-oggetto",
        da=CLIENTE, a=NOSTRO,
        oggetto=None,
        corpo=_corpo(["messaggio senza oggetto: quarantena, senza errori."]),
        giorni_fa=1,
    ))

    return messaggi


# Il file malformato non si costruisce con la libreria standard - che
# produrrebbe comunque un messaggio valido - ma si scrive a mano. E' il caso
# del quarto criterio di accettazione: deve finire in quarantena senza fermare
# gli altri.
MALFORMATO = (
    b"Questo file ha estensione .eml ma non e' un messaggio di posta.\r\n"
    b"Non ha intestazioni, non ha Message-ID, non ha mittente.\r\n"
    b"\x00\x01\x02 e qualche byte che non e' nemmeno testo.\r\n"
)


def scrivi(cartella: Path, messaggi: list[tuple[str, EmailMessage]]) -> int:
    """Scrive i file nella cartella. Restituisce quanti ne ha scritti.

    I file si sovrascrivono a ogni esecuzione: i messaggi sono sempre gli
    stessi, quindi riscriverli non aggiunge niente e non toglie niente. Quelli
    gia' elaborati stanno intanto in `elaborate/` e in `quarantena/`, che
    questo script non tocca.
    """
    cartella.mkdir(parents=True, exist_ok=True)

    for nome_file, messaggio in messaggi:
        # La politica SMTP serializza con gli a capo giusti (CRLF) e con le
        # intestazioni codificate come le codifica un programma di posta.
        (cartella / nome_file).write_bytes(messaggio.as_bytes(policy=SMTP))

    (cartella / "99-malformato.eml").write_bytes(MALFORMATO)

    return len(messaggi) + 1


def main() -> int:
    """Genera i messaggi. Restituisce il codice di uscita del processo."""
    cartella = settings.mail_local_dir

    print("Generazione dei messaggi di prova")
    print(f"  cartella: {cartella}")

    try:
        prodotti = _prodotti_di_prova()
    except Exception as errore:  # il database puo' non rispondere
        print(f"  ERRORE: il database non risponde ({errore})")
        print("  Controlla DATABASE_URL nel file .env.")
        return 2

    if not prodotti:
        print("  ERRORE: nel database non c'e' nessun prodotto con una versione.")
        print("  Creane almeno uno da /prodotti/nuovo, oppure esegui")
        print("  'python scripts/seed.py', e riprova.")
        return 1

    for codice, versione in prodotti:
        print(f"  prodotto usato: {codice} (ultima versione: {versione})")
    if len(prodotti) == 1:
        print("  NOTA: c'e' un prodotto solo, quindi tutti i messaggi")
        print("  riconoscibili finiranno su quello.")

    quanti = scrivi(cartella, costruisci(prodotti))

    print(f"  scritti {quanti} file .eml")
    print()
    print("Adesso apri http://localhost:8000/posta e premi «Elabora la posta».")
    print("Rieseguendo questo script e rielaborando, non deve comparire")
    print("nessun doppione: gli identificativi sono sempre gli stessi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
