"""La filigrana applicata al volo ai PDF delle versioni non piu' valide.

Il problema che risolve e' concreto e costoso: qualcuno scarica lo schema di
una versione di prodotto **superata**, se lo porta in officina, e ci costruisce
sopra. Il file, una volta uscito da Aurora, non ha piu' niente che dica da
dove viene e a che cosa apparteneva.

Per questo, quando si scarica un PDF che appartiene a una versione di prodotto
in stato "superato" o "obsoleto", il file **non** viene consegnato com'e': gli
viene stampata sopra una filigrana diagonale che dice tre cose - che la
versione e' superata, in quale stato si trova, e in che giorno e a che ora
quella copia e' stata scaricata. Cosi' un foglio stampato che gira per
l'azienda si riconosce a un metro di distanza.

**L'originale non si tocca.** La filigrana si applica a una copia in memoria,
al momento del download. Nell'archivio resta il file esattamente come e'
stato caricato, con la sua impronta: e' quello che permette di dimostrare, fra
tre anni, che il documento approvato non e' stato alterato (D-004).

**Solo i PDF.** Un DWG o uno ZIP non si possono marchiare senza rovinarli.
Per quelli il programma fa altre due cose, che stanno nelle rotte e non qui:
mostra un avviso a schermo prima del download e mette l'avvertenza dentro il
nome del file scaricato.

**Se la filigrana non riesce, il file si scarica lo stesso.** Un PDF cifrato,
o scritto male da un programma di trent'anni fa, puo' far fallire pypdf.
Rifiutare il download in quel caso vorrebbe dire togliere a una persona un
documento che ha il diritto di avere, per un problema che non la riguarda: si
consegna l'originale, l'avvertenza resta nel nome del file, e il guasto finisce
nel registro perche' qualcuno lo possa guardare.

COME E' FATTA, TECNICAMENTE. pypdf non disegna testo: sa unire pagine. Quindi
la pagina della filigrana viene costruita a mano, scrivendo le istruzioni di
disegno del PDF (un "flusso di contenuto") e dandole in pasto a pypdf, che le
sovrappone a ogni pagina del documento. Le istruzioni sono poche e sempre le
stesse: sposta l'origine al centro della pagina, ruota, scrivi tre righe di
testo in Helvetica semitrasparente. Helvetica e' uno dei quattordici caratteri
che ogni lettore di PDF ha per obbligo: non c'e' niente da incorporare e il
file non cresce.
"""

import io
import logging
import math
from datetime import datetime

from pypdf import PageObject, PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    FloatObject,
    NameObject,
    NumberObject,
)

from app.models import LifecycleState

logger = logging.getLogger("aurora.filigrana")

# Gli stati del ciclo di vita che fanno scattare la filigrana. Sono i due che
# vogliono dire "non e' piu' questa la versione buona".
STATI_DA_MARCHIARE: frozenset[LifecycleState] = frozenset(
    {LifecycleState.SUPERATO, LifecycleState.OBSOLETO}
)

# La dicitura chiesta dall'azienda, parola per parola.
DICITURA = "VERSIONE SUPERATA - non utilizzare per la produzione"

# L'avvertenza che finisce nel nome dei file che non sono PDF, dove la
# filigrana non si puo' stampare. Solo lettere maiuscole, trattini e nessun
# accento: diventa parte di un nome di file su Windows.
AVVERTENZA_NEL_NOME = "VERSIONE-SUPERATA"

# Il tipo MIME dei PDF. Sta qui perche' e' qui che si decide che cosa e' un
# PDF e che cosa non lo e'.
MIME_PDF = "application/pdf"

# Aspetto della filigrana. Sono misure tipografiche di questo componente, non
# valori del tema: restano scritte per esteso, come il bordo da un pixel della
# casella di spunta (docs/GUIDA_STILE.md, sezione 3).
CORPO_MASSIMO = 30.0  # dimensione del carattere della prima riga, in punti
CORPO_MINIMO = 7.0
INTERLINEA = 1.6  # quanto stacca una riga dall'altra, in multipli del corpo
OPACITA = 0.22  # 0 = invisibile, 1 = coprente
ANGOLO_GRADI = 38.0  # la diagonale, dal basso a sinistra all'alto a destra
LARGHEZZA_MEDIA_CARATTERE = 0.56  # in Helvetica, in multipli del corpo
QUOTA_DIAGONALE = 0.92  # quanto testo ci sta, sul massimo che ci starebbe

# Il nome con cui il carattere e lo stato di trasparenza vengono registrati
# nella pagina della filigrana. La coda "AuroraFiligrana" evita di scontrarsi
# con un nome gia' usato dal documento originale.
NOME_CARATTERE = "FAuroraFiligrana"
NOME_TRASPARENZA = "GSAuroraFiligrana"


def serve_filigrana(stato: LifecycleState | str | None) -> bool:
    """Dice se una versione di prodotto in quello stato va marchiata.

    Accetta anche la stringa scritta nel database, perche' e' quello che
    arriva quando lo stato viene letto da un'interrogazione grezza.
    """
    if stato is None:
        return False
    if isinstance(stato, LifecycleState):
        return stato in STATI_DA_MARCHIARE
    return any(stato == candidato.value for candidato in STATI_DA_MARCHIARE)


def e_un_pdf(mime_type: str | None, nome_file: str | None) -> bool:
    """Dice se il file e' un PDF, guardando prima il tipo e poi il nome.

    Il tipo dichiarato dal browser e' quello buono nella grande maggioranza
    dei casi; il nome serve per i browser e i sistemi che mandano
    "application/octet-stream" per qualunque cosa, che capita piu' spesso di
    quanto si creda.
    """
    if mime_type and mime_type.split(";")[0].strip().lower() == MIME_PDF:
        return True
    return bool(nome_file) and nome_file.lower().endswith(".pdf")


def righe_filigrana(
    stato: LifecycleState | str, momento: datetime
) -> tuple[str, str, str]:
    """Le tre righe stampate sopra il documento.

    Sono tre e non una perche' rispondono a tre domande diverse: che cosa
    non va (la dicitura), quanto non va (lo stato), e quanto e' vecchia questa
    copia (il momento dello scarico). L'ultima e' quella che permette di
    distinguere due stampe dello stesso file fatte a mesi di distanza.
    """
    testo_stato = stato.value if isinstance(stato, LifecycleState) else str(stato)
    return (
        DICITURA,
        f"Stato della versione: {testo_stato.replace('_', ' ')}",
        f"Scaricato il {momento.strftime('%d/%m/%Y')} alle "
        f"{momento.strftime('%H:%M')}",
    )


def nome_con_avvertenza(nome_file: str) -> str:
    """Il nome del file scaricato, con l'avvertenza davanti.

    "schema.dwg" diventa "VERSIONE-SUPERATA_schema.dwg". Serve ai formati su
    cui la filigrana non si puo' stampare: e' l'unico posto in cui
    l'avvertenza puo' viaggiare insieme al file dopo che e' uscito da Aurora.

    Un nome che ce l'ha gia' non se la prende due volte: succede quando si
    riscarica un file che era gia' stato scaricato e rimesso dentro.
    """
    pulito = (nome_file or "documento").strip() or "documento"
    if pulito.startswith(AVVERTENZA_NEL_NOME):
        return pulito
    return f"{AVVERTENZA_NEL_NOME}_{pulito}"


def _testo_pdf(testo: str) -> bytes:
    """Trasforma una riga di testo in una stringa letterale PDF.

    Nel PDF una stringa sta fra parentesi tonde, quindi le tonde e la barra
    rovesciata che compaiono nel testo vanno protette. I caratteri fuori
    dall'ASCII (accenti, lineette lunghe) si scrivono in ottale secondo la
    codifica WinAnsi, che e' quella dichiarata sul carattere: e' il modo in cui
    "e'" e "-" arrivano giusti anche stampati.
    """
    grezzo = testo.encode("cp1252", errors="replace")

    pezzi = bytearray(b"(")
    for byte in grezzo:
        if byte in b"()\\":
            pezzi += b"\\" + bytes([byte])
        elif 32 <= byte <= 126:
            pezzi.append(byte)
        else:
            pezzi += f"\\{byte:03o}".encode("ascii")
    pezzi += b")"

    return bytes(pezzi)


def _corpo_che_ci_sta(
    righe: tuple[str, str, str], larghezza: float, altezza: float
) -> float:
    """La dimensione del carattere piu' grande con cui le righe ci stanno.

    Il testo e' ruotato, quindi non basta confrontarne la lunghezza con la
    larghezza della pagina: una riga lunga L inclinata di un angolo occupa
    L*cos(angolo) in orizzontale e L*sin(angolo) in verticale, e deve starci
    tutte e due le volte. La riga piu' lunga possibile e' quindi

        L <= minimo fra larghezza/cos(angolo) e altezza/sin(angolo)

    Usare la diagonale della pagina, che sarebbe la risposta istintiva, e'
    sbagliato: la diagonale e' lunga quanto la riga soltanto se la riga e'
    inclinata **esattamente** come la diagonale. Con un A4 e un'inclinazione
    di 38 gradi il testo sborderebbe di una novantina di punti per parte.

    La larghezza del testo si stima moltiplicando il numero di caratteri per
    la larghezza media di Helvetica. E' una stima: sbagliare di qualche punto
    una filigrana non ha nessuna conseguenza, mentre misurarla per davvero
    vorrebbe dire portarsi dentro le tabelle delle metriche del carattere.
    """
    radianti = math.radians(ANGOLO_GRADI)
    lunghezza_massima = min(
        larghezza / math.cos(radianti), altezza / math.sin(radianti)
    ) * QUOTA_DIAGONALE

    piu_lunga = max(len(riga) for riga in righe)

    corpo = lunghezza_massima / (piu_lunga * LARGHEZZA_MEDIA_CARATTERE)
    return max(CORPO_MINIMO, min(CORPO_MASSIMO, corpo))


def _pagina_filigrana(
    larghezza: float, altezza: float, righe: tuple[str, str, str]
) -> PageObject:
    """Costruisce la pagina trasparente con sopra la filigrana.

    E' l'unico pezzo di Aurora che scrive istruzioni di disegno PDF a mano, e
    si legge dall'alto verso il basso come un elenco di ordini impartiti al
    lettore di PDF:

        q                       tieni da parte lo stato di adesso
        /GS.. gs                da qui in poi disegna semitrasparente
        1 0 0 1 cx cy cm        sposta l'origine al centro della pagina
        cos sin -sin cos 0 0 cm ruotala di ANGOLO_GRADI
        BT ... ET               scrivi il testo
        Q                       rimetti lo stato com'era

    Il testo e' centrato a occhio spostandolo a sinistra di meta' della sua
    larghezza stimata, per la stessa ragione per cui il corpo e' stimato.
    """
    corpo = _corpo_che_ci_sta(righe, larghezza, altezza)
    passo = corpo * INTERLINEA

    radianti = math.radians(ANGOLO_GRADI)
    coseno = math.cos(radianti)
    seno = math.sin(radianti)

    istruzioni = bytearray()
    istruzioni += b"q\n"
    istruzioni += f"/{NOME_TRASPARENZA} gs\n".encode("ascii")
    istruzioni += f"1 0 0 1 {larghezza / 2:.2f} {altezza / 2:.2f} cm\n".encode(
        "ascii"
    )
    istruzioni += (
        f"{coseno:.5f} {seno:.5f} {-seno:.5f} {coseno:.5f} 0 0 cm\n"
    ).encode("ascii")
    istruzioni += b"BT\n"
    istruzioni += f"/{NOME_CARATTERE} {corpo:.2f} Tf\n".encode("ascii")
    # Rosso spento: si legge sopra il bianco della pagina e sopra il nero del
    # disegno, ed e' il colore con cui in azienda si timbrano le copie non
    # valide. Non passa dalle variabili del foglio di stile perche' non e' un
    # colore dell'interfaccia: e' inchiostro dentro un file che uscira' da qui.
    istruzioni += b"0.72 0.12 0.12 rg\n"

    # Le tre righe, dall'alto verso il basso rispetto al centro.
    partenza = passo * (len(righe) - 1) / 2
    for numero, riga in enumerate(righe):
        # Il corpo delle righe dopo la prima e' piu' piccolo: la dicitura e'
        # l'informazione, le altre due sono il dettaglio.
        corpo_riga = corpo if numero == 0 else corpo * 0.62
        istruzioni += f"/{NOME_CARATTERE} {corpo_riga:.2f} Tf\n".encode("ascii")

        larghezza_riga = len(riga) * corpo_riga * LARGHEZZA_MEDIA_CARATTERE
        x = -larghezza_riga / 2
        y = partenza - numero * passo

        istruzioni += b"1 0 0 1 0 0 Tm\n"
        istruzioni += f"{x:.2f} {y:.2f} Td\n".encode("ascii")
        istruzioni += _testo_pdf(riga) + b" Tj\n"
    istruzioni += b"ET\nQ\n"

    pagina = PageObject.create_blank_page(width=larghezza, height=altezza)

    contenuto = DecodedStreamObject()
    contenuto.set_data(bytes(istruzioni))
    pagina[NameObject("/Contents")] = contenuto

    carattere = DictionaryObject()
    carattere[NameObject("/Type")] = NameObject("/Font")
    carattere[NameObject("/Subtype")] = NameObject("/Type1")
    carattere[NameObject("/BaseFont")] = NameObject("/Helvetica-Bold")
    carattere[NameObject("/Encoding")] = NameObject("/WinAnsiEncoding")

    trasparenza = DictionaryObject()
    trasparenza[NameObject("/Type")] = NameObject("/ExtGState")
    # ca governa i riempimenti, CA i contorni: si mettono tutti e due,
    # altrimenti un lettore che disegna il testo come contorno lo farebbe
    # coprente.
    trasparenza[NameObject("/ca")] = FloatObject(OPACITA)
    trasparenza[NameObject("/CA")] = FloatObject(OPACITA)

    caratteri = DictionaryObject()
    caratteri[NameObject(f"/{NOME_CARATTERE}")] = carattere

    stati = DictionaryObject()
    stati[NameObject(f"/{NOME_TRASPARENZA}")] = trasparenza

    risorse = DictionaryObject()
    risorse[NameObject("/Font")] = caratteri
    risorse[NameObject("/ExtGState")] = stati
    risorse[NameObject("/ProcSet")] = ArrayObject(
        [NameObject("/PDF"), NameObject("/Text")]
    )

    pagina[NameObject("/Resources")] = risorse
    pagina[NameObject("/MediaBox")] = ArrayObject(
        [
            NumberObject(0),
            NumberObject(0),
            FloatObject(larghezza),
            FloatObject(altezza),
        ]
    )

    return pagina


class FiligranaNonApplicata(Exception):
    """Il PDF non si e' lasciato marchiare.

    Chi la cattura consegna l'originale: il download non si nega per un
    problema che non riguarda chi sta scaricando.
    """


def applica(
    contenuto: bytes, *, stato: LifecycleState | str, momento: datetime
) -> bytes:
    """Restituisce il PDF con la filigrana stampata su ogni pagina.

    Ogni pagina ha la sua filigrana costruita sulla propria misura: un
    documento con dentro un A4 e un A0 - normale per gli schemi elettrici -
    avrebbe altrimenti la filigrana giusta su uno e fuori posto sull'altro.

    Solleva FiligranaNonApplicata quando il PDF non si apre o non si scrive:
    e' l'unico caso in cui il file esce da qui com'era.
    """
    try:
        lettore = leggi_pdf(contenuto)
        scrittore = PdfWriter()

        righe = righe_filigrana(stato, momento)

        for pagina in lettore.pages:
            riquadro = pagina.mediabox
            larghezza = float(riquadro.width)
            altezza = float(riquadro.height)

            filigrana = _pagina_filigrana(larghezza, altezza, righe)
            # over=True: la filigrana va **sopra** il disegno, altrimenti un
            # documento con lo sfondo pieno se la mangerebbe.
            pagina.merge_page(filigrana, over=True)
            scrittore.add_page(pagina)

        return _in_byte(scrittore)

    except FiligranaNonApplicata:
        raise
    except Exception as errore:
        # Un except largo, e qui e' voluto: pypdf solleva una decina di tipi
        # di errore diversi a seconda di che cosa non gli piace del file, e
        # l'elenco cambia da una versione all'altra. Quello che conta e' che
        # nessuno di essi debba poter impedire un download. L'errore non viene
        # ingoiato: viene registrato con la sua traccia e trasformato in una
        # sola eccezione che chi chiama sa gestire.
        logger.exception("Filigrana non applicata: %s", errore)
        raise FiligranaNonApplicata(str(errore)) from errore


def leggi_pdf(contenuto: bytes) -> PdfReader:
    """Apre un PDF che sta in memoria.

    Sta in una funzione sua perche' la usano sia applica() sia i test, che
    rileggono il risultato della filigrana per verificare che ci sia davvero.
    """
    return PdfReader(io.BytesIO(contenuto))


def _in_byte(scrittore: PdfWriter) -> bytes:
    """Il PDF composto, come sequenza di byte pronta da mandare al browser."""
    uscita = io.BytesIO()
    scrittore.write(uscita)
    return uscita.getvalue()


def testo_di(contenuto: bytes) -> str:
    """Tutto il testo di un PDF, una pagina dopo l'altra.

    Serve ai test: e' il modo in cui si verifica che la filigrana c'e'
    davvero, invece di fidarsi del fatto che la funzione non ha sollevato
    errori.
    """
    lettore = leggi_pdf(contenuto)
    return "\n".join(pagina.extract_text() or "" for pagina in lettore.pages)
