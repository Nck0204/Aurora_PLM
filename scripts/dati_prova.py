"""Riempie il database con un volume di dati realistico.

Serve a rispondere a una domanda sola, che fino alla sessione 13 nessuno
aveva potuto fare: **le pagine restano veloci quando dentro c'e' il lavoro di
due anni?** Con tre prodotti e otto documenti qualunque interrogazione sembra
istantanea, anche quella scritta male.

Quello che scrive, di partenza:

    15 persone        due creatori e tredici fra ingegneri, responsabili e
                      lettori, con le loro assegnazioni ai progetti
     8 clienti        con qualche contatto ciascuno
    20 prodotti       con il codice che si scompone secondo la regola in uso
    40 versioni       la 1 di ogni prodotto piu' una derivata, in stati
                      diversi del ciclo di vita
    ~30 progetti      aperti sulle versioni, avanzati di qualche fase,
                      qualcuno chiuso
   300 documenti      distribuiti sui progetti, con tipi e classificazioni
                      diversi e qualche versione successiva
   500 messaggi       archiviati passando dal motore vero, con allegati,
                      attribuzione automatica e quarantena

Come si esegue, dalla radice del progetto e con l'ambiente virtuale attivo:

    python scripts/dati_prova.py

Poi si misurano i tempi delle pagine con:

    python scripts/misura_tempi.py


DOVE SCRIVE, E PERCHE' VA SAPUTO
--------------------------------

**Scrive nel database indicato da DATABASE_URL**, cioe' quello vero. Non e'
una svista ed e' l'unico modo di misurare qualcosa che valga: un tempo di
risposta misurato su un database finto non dice niente del database vero, che
ha i suoi indici, la sua cache e le sue statistiche.

**Non cancella niente** (regola 5 di CLAUDE.md), nemmeno quello che ha scritto
lui. Su un server in esercizio **non si esegue**: e' uno strumento da macchina
di sviluppo e da ambiente di prova. Lo dice anche prima di cominciare, e
chiede conferma.


PERCHE' I DATI SI GENERANO INVECE DI SCRIVERLI
----------------------------------------------

Tutti i valori unici - codici cliente, codici prodotto, nomi utente,
identificativi dei messaggi, contenuto dei file - portano una **coda casuale
comune a tutto il lotto**. E' la stessa medicina che tests/conftest.py applica
ai test, e per la stessa ragione: il database contiene gia' dati veri lasciati
dalle verifiche a mano delle sessioni precedenti, e un codice inventato a
tavolino prima o poi collide con uno di quelli. Quando collide, non si rompe
la generazione: si rompe il vincolo di unicita' a meta' lavoro, con il
database riempito per tre quarti.

La coda si stampa in cima all'esecuzione, cosi' si sa riconoscere che cosa ha
scritto un lotto: i codici prodotto cominciano tutti per `PRV<coda>`.


PERCHE' PASSA DAI SERVIZI E NON SCRIVE LE RIGHE A MANO
-------------------------------------------------------

Ogni cosa viene creata chiamando la stessa funzione che chiama l'interfaccia:
`products.crea_prodotto()`, `projects.apri_progetto()`,
`documents.crea_documento()`, `emails.acquisisci()`. Costa qualche minuto in
piu' di esecuzione e restituisce dati **veri**: i codici scomposti come li
scompone il programma, le righe del registro delle operazioni con la loro
catena di impronte, i file depositati per impronta con la deduplicazione, i
messaggi attribuiti dalle stesse quattro regole.

Un generatore che scrivesse le righe a mano produrrebbe un database che
somiglia a quello vero e si comporta in un altro modo - a cominciare dal
registro, che resterebbe vuoto proprio mentre si misura la pagina che lo
mostra.
"""

import argparse
import io
import random
import string
import sys
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import format_datetime
from pathlib import Path

# Lo script si esegue dalla riga di comando: senza questa riga "import app"
# non funzionerebbe, perche' scripts/ non e' nel percorso di ricerca.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    Classification,
    GlobalRole,
    LifecycleState,
    PhaseTemplate,
    Product,
    ProductVersion,
    Project,
    User,
)
from app.services import (  # noqa: E402
    customers,
    documents,
    emails,
    lifecycle,
    mail_source,
    phases,
    products,
    projects,
    storage,
    users,
)

# --- Quanto se ne fa, di partenza -------------------------------------------
#
# Sono i numeri chiesti dalla sessione 13. Si cambiano dalla riga di comando
# quando serve un volume diverso: `--documenti 3000` risponde alla domanda
# "e fra cinque anni?".

UTENTI = 15
CLIENTI = 8
PRODOTTI = 20
VERSIONI = 40
DOCUMENTI = 300
MESSAGGI = 500

# Ogni quanti messaggi si stampa una riga di avanzamento. Un generatore che
# per due minuti non dice niente sembra bloccato.
PASSO_AVANZAMENTO = 50

# --- Il vocabolario da cui si compongono i dati finti ------------------------
#
# Sono parole del mestiere di quest'azienda: convertitori, alimentatori,
# schede di controllo per il ferroviario. Servono a far somigliare gli elenchi
# a quelli veri, perche' una pagina si legge diversamente quando le righe
# hanno senso.

RAGIONI_SOCIALI = (
    "Ferrovie Nord Milano",
    "Trasporti Regionali Veneto",
    "Metropolitana di Genova",
    "Officine Meccaniche Padane",
    "Elettrotecnica Bresciana",
    "Impianti Ferroviari Toscani",
    "Automazione Industriale Emilia",
    "Costruzioni Elettriche Adriatiche",
    "Sistemi di Bordo Piemonte",
    "Tecnologie Ferroviarie Alpine",
)

NOMI = (
    "Marco", "Anna", "Luca", "Chiara", "Paolo", "Giulia", "Andrea", "Elena",
    "Stefano", "Francesca", "Davide", "Silvia", "Roberto", "Laura", "Matteo",
    "Valentina", "Alessandro", "Martina",
)

COGNOMI = (
    "Bertoli", "Ferrari", "Conti", "Ricci", "Marino", "Greco", "Gallo",
    "Costa", "Fontana", "Caruso", "Rizzo", "Lombardi", "Moretti", "Barbieri",
    "Mancini", "Rinaldi", "Villa", "Sartori",
)

# Le varianti del codice prodotto. La regola di config/codice_prodotto.toml
# legge modello, potenza, tensione di ingresso, tensione di uscita e variante:
# questi valori la rispettano, cosi' i prodotti generati si scompongono come
# si scompongono quelli veri e i filtri della ricerca hanno qualcosa da
# filtrare.
POTENZE = ("600", "1100", "1500", "2200", "3000")
INGRESSI = ("24", "48", "110")
USCITE = ("24", "110", "230")
VARIANTI = ("SW", "HW", "DC", "AC")

DESCRIZIONI_PRODOTTO = (
    "Convertitore statico per servizi di bordo",
    "Alimentatore ausiliario a doppio ingresso",
    "Scheda di controllo per azionamento di trazione",
    "Gruppo di continuita' per cabina di guida",
    "Modulo di isolamento per rete di segnalamento",
    "Regolatore di tensione per illuminazione interna",
)

TITOLI_DOCUMENTO = (
    "Schema elettrico di potenza",
    "Schema di cablaggio",
    "Disegno di assieme del telaio",
    "Distinta base preliminare",
    "Specifica di collaudo",
    "Rapporto di prova climatica",
    "Certificato di conformita'",
    "Analisi termica del dissipatore",
    "Manuale di installazione",
    "Verbale di riesame di progetto",
    "Piano della qualita'",
    "Offerta tecnico-economica",
    "Relazione di calcolo",
    "Layout del circuito stampato",
    "Firmware di controllo",
)

# I tipi di documento sono quelli di config/tipi_documento.toml. Si scrivono
# qui perche' questo script deve poter girare anche se quel file manca - e
# perche' un tipo che non e' in elenco viene accettato lo stesso (D-050).
TIPI_DOCUMENTO = (
    "Schema elettrico",
    "PCB",
    "Meccanica",
    "Firmware",
    "Specifica",
    "Rapporto di prova",
    "Certificato",
    "Altro",
)

MOTIVI_DERIVAZIONE = (
    "Richiesta del cliente: aumento della potenza nominale.",
    "Obsolescenza del componente di potenza: sostituito con equivalente.",
    "Correzione di un difetto riscontrato in collaudo.",
    "Adeguamento alla revisione della norma EN 50155.",
    "Variante per un secondo cliente, con connettori diversi.",
)

OGGETTI_MESSAGGIO = (
    "Richiesta di chiarimento sullo schema di potenza",
    "Conferma della data di consegna",
    "Trasmissione del verbale di collaudo",
    "Deroga concordata sulla temperatura di esercizio",
    "Richiesta di offerta per ricambi",
    "Segnalazione di anomalia in esercizio",
    "Aggiornamento del piano di consegna",
    "Documentazione per l'omologazione",
)

DOMINIO_PROVA = "prova.aurora.local"


# --- Attrezzi ---------------------------------------------------------------


def coda_del_lotto() -> str:
    """La coda casuale che rende unico tutto quello che questo giro scrive.

    Sei lettere bastano: sono trecento milioni di combinazioni, e il rischio
    che due lotti si scontrino e' molto piu' basso di quello che si corre
    scrivendo un codice a mano.

    **Solo lettere, niente cifre**, ed e' la stessa ragione per cui
    `tests/conftest.py` fa cosi' in `modello_irripetibile()`: questa coda
    finisce dentro la sigla del modello, e nell'espressione di scomposizione
    il modello e' il gruppo delle lettere iniziali. Una cifra qui dentro
    spezza il gruppo, il codice non si scompone piu' e i venti prodotti del
    lotto nascono tutti con `code_parts` vuoto - il che, per la regola D-039,
    non e' un errore ma rende inutile meta' della ricerca che si voleva
    misurare.
    """
    return "".join(random.choices(string.ascii_uppercase, k=6))


def modello_di(coda: str, numero: int) -> str:
    """La sigla di modello di un prodotto del lotto.

    Solo lettere, come vuole l'espressione di scomposizione: una cifra qui
    finirebbe dentro la potenza e cambierebbe il significato del codice.
    """
    lettere = "".join(
        chr(ord("A") + (numero // (26**posizione)) % 26) for posizione in range(2)
    )
    return f"PRV{coda}{lettere}"


def contenuto_di_prova(seme: str, kilobyte: int = 4) -> bytes:
    """Il contenuto di un file, diverso da qualunque altro.

    L'archivio deposita per impronta (D-004): due file con lo stesso contenuto
    diventano un file solo. Se questo script scrivesse sempre gli stessi byte,
    trecento documenti occuperebbero **un** oggetto sul disco, e la pagina di
    diagnostica direbbe una cosa che in produzione non succedera' mai.

    Il seme viene dal titolo e dal numero del documento, quindi due file
    diversi hanno contenuto diverso e lo stesso file rigenerato ha lo stesso
    contenuto.
    """
    generatore = random.Random(seme)
    alfabeto = string.ascii_letters + string.digits + " \n"
    corpo = "".join(generatore.choices(alfabeto, k=kilobyte * 1024))
    return f"[Aurora - dati di prova - {seme}]\n{corpo}".encode("utf-8")


def pdf_di_prova(seme: str, pagine: int = 2) -> bytes:
    """Un PDF vero e vuoto, che pypdf sa aprire.

    Serve perche' la filigrana delle versioni superate (D-046) e' un pezzo di
    programma che si esercita solo su un PDF vero: un file con dentro del
    testo e l'estensione `.pdf` non lo esercita affatto.
    """
    from pypdf import PageObject, PdfWriter

    scrittore = PdfWriter()
    for _ in range(pagine):
        scrittore.add_page(PageObject.create_blank_page(width=595, height=842))
    scrittore.add_metadata({"/Title": f"Aurora dati di prova {seme}"})

    uscita = io.BytesIO()
    scrittore.write(uscita)
    return uscita.getvalue()


def quando(giorni_fa: int, ora: int = 9) -> datetime:
    """Una data realistica, calcolata all'indietro a partire da oggi."""
    momento = datetime.now(timezone.utc) - timedelta(days=giorni_fa)
    return momento.replace(hour=ora, minute=0, second=0, microsecond=0)


class Passo:
    """Stampa una riga per ogni fase della generazione, con il tempo che costa.

    Non e' un ornamento: la generazione dura qualche minuto, e chi la lancia
    deve poter distinguere "sta lavorando" da "si e' piantata".
    """

    def __init__(self, titolo: str) -> None:
        self.titolo = titolo
        self.inizio = 0.0

    def __enter__(self) -> "Passo":
        print(f"  {self.titolo}...", end="", flush=True)
        self.inizio = time.perf_counter()
        return self

    def __exit__(self, *_) -> None:
        print(f" fatto in {time.perf_counter() - self.inizio:.1f}s")


# --- Le persone -------------------------------------------------------------


def crea_le_persone(db: Session, coda: str, quanti: int) -> list[User]:
    """Crea le persone del lotto e restituisce l'elenco.

    **I nomi utente hanno due punti** (`prova.marco.bertoli.AB12CD`), come
    quelli dei test: `users.proponi_username()` ne compone al massimo uno, per
    cui quello spazio di nomi il programma non lo raggiunge mai e una persona
    vera creata dall'interfaccia non ci puo' collidere.

    Le prime due sono creatori: servono a provare le pagine riservate, e una
    sola non basterebbe a provare che cosa succede quando ce ne sono due.
    """
    autore = primo_creatore(db)
    creati: list[User] = []

    for numero in range(quanti):
        nome = NOMI[numero % len(NOMI)]
        cognome = COGNOMI[numero % len(COGNOMI)]
        username = f"prova.{nome.lower()}.{cognome.lower()}.{coda}{numero:02d}"
        ruolo = GlobalRole.CREATORE if numero < 2 else GlobalRole.UTENTE

        utente, _password = users.crea_utente(
            db,
            first_name=nome,
            last_name=cognome,
            email=f"{username}@{DOMINIO_PROVA}",
            username=username,
            ruolo=ruolo,
            creato_da=autore,
        )
        # La password generata non serve a nessuno: queste persone non entrano
        # mai. Chi volesse entrare come una di loro se ne assegna una con
        # scripts/reimposta_password.py, che e' la strada di sempre.
        creati.append(utente)

    db.commit()
    return creati


def primo_creatore(db: Session) -> User:
    """Un creatore attivo del database, da usare come autore delle operazioni.

    Ogni riga del registro delle operazioni vuole un autore, e mettere `None`
    - che vuol dire "il programma da solo" - sarebbe scrivere una cosa falsa
    (D-042). Si prende un creatore vero: su un database appena installato e'
    `admin`, quello di scripts/seed.py.
    """
    trovato = db.scalars(
        select(User)
        .where(User.global_role == GlobalRole.CREATORE, User.is_active.is_(True))
        .order_by(User.created_at)
    ).first()

    if trovato is None:
        raise SystemExit(
            "\n  Errore: nel database non c'e' nessun creatore attivo.\n"
            "  Esegui prima 'python scripts/seed.py', oppure apri\n"
            "  http://localhost:8000/primo-avvio e crea il primo profilo.\n"
        )
    return trovato


# --- I clienti --------------------------------------------------------------


def crea_i_clienti(db: Session, coda: str, quanti: int, autore: User) -> list:
    """Crea i clienti del lotto, ciascuno con due contatti."""
    creati = []

    for numero in range(quanti):
        ragione = RAGIONI_SOCIALI[numero % len(RAGIONI_SOCIALI)]
        cliente = customers.crea_cliente(
            db,
            nome=f"{ragione} ({coda})",
            codice=f"P{coda}{numero:02d}",
            note="Cliente generato da scripts/dati_prova.py.",
            autore=autore,
        )
        for indice in range(2):
            nome = NOMI[(numero + indice) % len(NOMI)]
            cognome = COGNOMI[(numero + indice + 3) % len(COGNOMI)]
            customers.aggiungi_contatto(
                db,
                cliente=cliente,
                nome=f"{nome} {cognome}",
                ruolo="Ufficio tecnico" if indice == 0 else "Ufficio acquisti",
                email=f"{nome.lower()}.{cognome.lower()}@{coda.lower()}.esempio",
                autore=autore,
            )
        creati.append(cliente)

    db.commit()
    return creati


# --- I prodotti e le versioni ------------------------------------------------


def crea_i_prodotti(
    db: Session,
    coda: str,
    quanti: int,
    quante_versioni: int,
    clienti: list,
    autore: User,
) -> list[tuple[Product, list[ProductVersion]]]:
    """Crea i prodotti con le loro versioni, in stati diversi del ciclo di vita.

    Ogni prodotto nasce con la versione 1 (D-040). Alle prime
    `quante_versioni - quanti` versioni si aggiunge una derivata, cosi' il
    conto delle versioni torna esattamente con quello chiesto.

    Gli stati non sono tutti uguali di proposito: una parte dei prodotti resta
    in sviluppo, una parte viene rilasciata - e allora la versione precedente
    passa da sola a «superato», che e' il pezzo di programma che vale la pena
    esercitare - e qualcuna arriva in produzione.
    """
    generatore = random.Random(f"prodotti-{coda}")
    da_derivare = max(0, quante_versioni - quanti)
    risultato: list[tuple[Product, list[ProductVersion]]] = []

    for numero in range(quanti):
        codice = (
            f"{modello_di(coda, numero)}"
            f"{POTENZE[numero % len(POTENZE)]}"
            f"-{INGRESSI[numero % len(INGRESSI)]}"
            f"-{USCITE[numero % len(USCITE)]}"
            f"{VARIANTI[numero % len(VARIANTI)]}"
        )
        prodotto, prima = products.crea_prodotto(
            db,
            codice=codice,
            cliente=clienti[numero % len(clienti)],
            descrizione=DESCRIZIONI_PRODOTTO[numero % len(DESCRIZIONI_PRODOTTO)],
            autore=autore,
        )
        versioni = [prima]

        if numero < da_derivare:
            seconda = products.deriva_versione(
                db,
                origine=prima,
                motivazione=MOTIVI_DERIVAZIONE[numero % len(MOTIVI_DERIVAZIONE)],
                autore=autore,
            )
            versioni.append(seconda)

        risultato.append((prodotto, versioni))
        db.flush()

    db.commit()

    # Gli stati si muovono in un secondo giro, dopo che tutte le versioni
    # esistono: il superamento automatico guarda la versione precedente dello
    # stesso prodotto, e con le versioni create a meta' non troverebbe niente
    # da superare.
    for numero, (_prodotto, versioni) in enumerate(risultato):
        percorso = generatore.choice(
            (
                (),
                (LifecycleState.RILASCIATO,),
                (LifecycleState.RILASCIATO, LifecycleState.IN_PRODUZIONE),
            )
        )
        for stato in percorso:
            lifecycle.cambia_stato(
                db,
                versione=versioni[-1],
                nuovo_stato=stato,
                autore=autore,
                motivazione=None,
            )
        db.flush()

    db.commit()
    return risultato


# --- I progetti --------------------------------------------------------------


def modello_di_fasi(db: Session) -> PhaseTemplate:
    """Il modello di fasi con cui aprire i progetti del lotto.

    Si prende il primo proponibile, che su un'installazione normale e' lo
    «Standard» di scripts/seed.py. Se non ce n'e' nessuno lo script si ferma
    invece di inventarne uno: le fasi sono dati dell'azienda (D-055), e un
    percorso inventato da un generatore non e' un percorso su cui misurare
    niente.
    """
    attivi = phases.modelli_di_fasi(db)
    if not attivi:
        raise SystemExit(
            "\n  Errore: nel database non c'e' nessun modello di fasi "
            "proponibile.\n"
            "  Esegui prima 'python scripts/seed.py', oppure creane uno da\n"
            "  http://localhost:8000/fasi.\n"
        )
    return attivi[0]


def apri_i_progetti(
    db: Session,
    coda: str,
    prodotti: list[tuple[Product, list[ProductVersion]]],
    persone: list[User],
    autore: User,
) -> list[Project]:
    """Apre un progetto su tre versioni su quattro e ne fa avanzare le fasi.

    Non su tutte, e non e' un risparmio: in azienda ci sono versioni su cui un
    progetto non e' mai stato aperto - quelle nate per un'offerta che non e'
    andata in porto - ed e' un caso che il programma deve trattare. La posta
    che arriva su una di quelle e' il caso previsto da D-069.

    L'avanzamento delle fasi e' casuale ma ripetibile: alcuni progetti restano
    nella prima fase, altri arrivano in fondo e si chiudono. Un cruscotto in
    cui tutti i progetti sono al primo passo non somiglia a niente.
    """
    generatore = random.Random(f"progetti-{coda}")
    modello = modello_di_fasi(db)
    aperti: list[Project] = []

    for _prodotto, versioni in prodotti:
        for versione in versioni:
            if generatore.random() > 0.75:
                continue

            responsabile = generatore.choice(persone)
            squadra = generatore.sample(persone, k=min(3, len(persone)))
            lettori = generatore.sample(persone, k=min(2, len(persone)))

            progetto = projects.apri_progetto(
                db,
                versione=versione,
                project_manager=responsabile,
                modello=modello,
                norme=["EN 50155", "EN 50121-3-2"],
                ingegneri=[p for p in squadra if p.id != responsabile.id],
                lettori=[p for p in lettori if p.id != responsabile.id],
                autore=autore,
            )
            aperti.append(progetto)
            db.flush()

    db.commit()

    for progetto in aperti:
        quanti_passi = generatore.randint(0, 5)
        for _ in range(quanti_passi):
            if phases.fase_successiva(db, progetto) is None:
                break
            try:
                phases.avanza(
                    db,
                    progetto=progetto,
                    autore=autore,
                    motivazione="Avanzamento generato da scripts/dati_prova.py.",
                )
            except phases.PassaggioNonAmmesso:
                # Un progetto chiuso non avanza piu': e' esattamente quello
                # che deve succedere, e non e' un errore di questo script.
                break
        db.flush()

    db.commit()
    return aperti


# --- I documenti -------------------------------------------------------------


def classificazioni_attive(db: Session) -> list[Classification]:
    """Le classificazioni con cui si possono creare documenti.

    Sono quelle di scripts/seed.py, meno quelle disattivate: caricare su una
    classificazione disattivata e' vietato (D-054), e un generatore che ci
    provasse si fermerebbe a meta'.
    """
    trovate = list(
        db.scalars(
            select(Classification)
            .where(Classification.is_active.is_(True))
            .order_by(Classification.sort_order)
        ).all()
    )
    if not trovate:
        raise SystemExit(
            "\n  Errore: nel database non c'e' nessuna classificazione "
            "attiva.\n"
            "  Esegui prima 'python scripts/seed.py'.\n"
        )
    return trovate


def crea_i_documenti(
    db: Session,
    coda: str,
    quanti: int,
    progetti_aperti: list[Project],
    persone: list[User],
) -> int:
    """Distribuisce i documenti sui progetti, con stati e versioni diversi.

    **Un documento su sei e' un PDF vero**, cosi' la filigrana delle versioni
    superate ha qualcosa su cui lavorare quando si prova lo scarico.

    **Un documento su cinque riceve una seconda versione**, e uno su quattro
    viene portato avanti nel suo ciclo di vita: senza, l'elenco dei documenti
    mostrerebbe trecento righe tutte in bozza e i filtri per stato non
    filtrerebbero niente.

    I documenti si scrivono solo sui progetti **non chiusi**: su un progetto
    chiuso il caricamento e' vietato per tutti tranne il creatore (D-058), e
    aggirare quella regola da qui vorrebbe dire riempire il database di righe
    che dall'interfaccia non si sarebbero potute creare.
    """
    generatore = random.Random(f"documenti-{coda}")
    classi = classificazioni_attive(db)
    aperti = [p for p in progetti_aperti if p.closed_at is None]

    if not aperti:
        print("\n  Nessun progetto aperto: i documenti non si possono creare.")
        return 0

    creati = 0
    for numero in range(quanti):
        progetto = aperti[numero % len(aperti)]
        autore = generatore.choice(persone)
        titolo = TITOLI_DOCUMENTO[numero % len(TITOLI_DOCUMENTO)]
        seme = f"{coda}-doc-{numero:04d}"

        if numero % 6 == 0:
            contenuto = pdf_di_prova(seme)
            nome_file = f"{seme}.pdf"
            mime = "application/pdf"
        else:
            contenuto = contenuto_di_prova(seme)
            nome_file = f"{seme}.txt"
            mime = "text/plain"

        deposito = storage.deposita(io.BytesIO(contenuto))
        caricamento = documents.Caricamento(
            sorgente=io.BytesIO(contenuto),
            nome_file=nome_file,
            mime_type=mime,
        )
        documento, _versione = documents.crea_documento(
            db,
            progetto=progetto,
            titolo=f"{titolo} - rev. {numero % 9}",
            tipo=TIPI_DOCUMENTO[numero % len(TIPI_DOCUMENTO)],
            classificazione=classi[numero % len(classi)],
            caricamento=caricamento,
            deposito=deposito,
            autore=autore,
        )
        creati += 1

        if numero % 5 == 0:
            seme_due = f"{seme}-v2"
            contenuto_due = contenuto_di_prova(seme_due)
            deposito_due = storage.deposita(io.BytesIO(contenuto_due))
            documents.aggiungi_versione(
                db,
                documento=documento,
                caricamento=documents.Caricamento(
                    sorgente=io.BytesIO(contenuto_due),
                    nome_file=nome_file,
                    mime_type=mime,
                ),
                deposito=deposito_due,
                nota="Correzione delle quote dopo il riesame.",
                autore=autore,
            )

        if numero % 4 == 0:
            _porta_avanti(db, documento, autore, generatore)

        if numero % 25 == 0:
            db.commit()

    db.commit()
    return creati


def _porta_avanti(db: Session, documento, autore: User, generatore) -> None:
    """Fa fare al documento un pezzo del suo ciclo di vita.

    Il percorso e' quello del grafo di `lifecycle.py`, un passo per volta:
    non si scrive uno stato addosso al documento, si chiede al servizio di
    cambiarlo. Cosi' i passaggi che il grafo non ammette non capitano, e le
    righe del registro raccontano gli stessi fatti che racconterebbero se a
    premere il pulsante fosse stata una persona.
    """
    from app.models import DocumentState

    percorso = generatore.choice(
        (
            (DocumentState.IN_VERIFICA,),
            (DocumentState.IN_VERIFICA, DocumentState.RILASCIATO),
            (DocumentState.IN_VERIFICA, DocumentState.BOZZA),
        )
    )
    for stato in percorso:
        try:
            documents.cambia_stato(
                db,
                documento=documento,
                nuovo_stato=stato,
                autore=autore,
            )
        except lifecycle.TransizioneNonAmmessa:
            break


# --- I messaggi di posta ------------------------------------------------------


def scrivi_i_messaggi(
    cartella: Path,
    coda: str,
    quanti: int,
    prodotti: list[tuple[Product, list[ProductVersion]]],
) -> int:
    """Scrive i file .eml nella cartella della posta, pronti da acquisire.

    **Tre quarti dei messaggi nominano un prodotto vero** e verranno
    attribuiti; il resto no e finira' in quarantena. E' una proporzione
    verosimile, ed e' anche quella che rende la pagina della quarantena
    qualcosa che si puo' guardare.

    Un messaggio su otto e' una risposta a quello precedente: e' la terza via
    di attribuzione, quella che segue il filo della conversazione, e senza
    conversazioni non si esercita.
    """
    generatore = random.Random(f"posta-{coda}")
    cartella.mkdir(parents=True, exist_ok=True)

    codici = [
        (prodotto.code, len(versioni)) for prodotto, versioni in prodotti
    ]
    precedente: str | None = None
    scritti = 0

    for numero in range(quanti):
        nome = f"{coda}-{numero:04d}"
        identificativo = f"<lotto-{nome}@{DOMINIO_PROVA}>"
        soggetto_base = OGGETTI_MESSAGGIO[numero % len(OGGETTI_MESSAGGIO)]

        messaggio = EmailMessage()
        messaggio["Message-ID"] = identificativo
        messaggio["From"] = f"cliente{numero % 20}@{coda.lower()}.esempio"
        messaggio["To"] = f"ufficio.tecnico@{DOMINIO_PROVA}"
        messaggio["Date"] = format_datetime(quando(numero % 400, 8 + numero % 9))

        risposta = precedente is not None and numero % 8 == 0

        if risposta:
            messaggio["Subject"] = f"R: {soggetto_base}"
            messaggio["In-Reply-To"] = precedente
            messaggio["References"] = precedente
        elif generatore.random() < 0.75 and codici:
            codice, quante_versioni = generatore.choice(codici)
            numero_versione = generatore.randint(1, quante_versioni)
            messaggio["Subject"] = (
                f"[{codice}][V{numero_versione}][SPECS] {soggetto_base}"
            )
        else:
            messaggio["Subject"] = soggetto_base

        messaggio.set_content(
            f"Buongiorno,\n\n{soggetto_base}.\n\n"
            f"Riferimento interno: {nome}.\n\n"
            "Cordiali saluti\n"
        )

        # Un messaggio su dieci porta un allegato: gli allegati sono la meta'
        # del peso della posta, e una casella senza allegati non misura niente.
        if numero % 10 == 0:
            messaggio.add_attachment(
                contenuto_di_prova(f"{coda}-all-{numero:04d}", kilobyte=32),
                maintype="application",
                subtype="octet-stream",
                filename=f"allegato-{nome}.dat",
            )

        (cartella / f"{nome}.eml").write_bytes(messaggio.as_bytes(policy=SMTP))
        scritti += 1
        precedente = identificativo

    return scritti


def acquisisci_i_messaggi(db: Session, autore: User, attesi: int) -> int:
    """Fa girare il motore di acquisizione finche' la cartella non e' vuota.

    Il motore ne prende al massimo `MESSAGGI_PER_GIRO` per volta - e' la
    protezione contro la cartella con dentro dieci anni di posta - quindi con
    piu' messaggi di cosi' servono piu' giri.
    """
    fonte = mail_source.FonteLocale()
    fonte.prepara()

    archiviati = 0
    while True:
        riepilogo = emails.acquisisci(db, fonte, autore=autore)
        if riepilogo.letti == 0:
            break
        archiviati += riepilogo.archiviati + riepilogo.in_quarantena
        print(
            f"    giro: {riepilogo.letti} letti, "
            f"{riepilogo.archiviati} attribuiti, "
            f"{riepilogo.in_quarantena} in quarantena, "
            f"{riepilogo.errori} errori"
        )
        if archiviati >= attesi:
            break

    return archiviati


# --- Il conto finale ----------------------------------------------------------


def conta(db: Session) -> dict[str, int]:
    """Quante righe ci sono adesso nelle tabelle che contano."""
    from app.models import (
        AuditLog,
        Customer,
        Document,
        DocumentVersion,
        EmailAttachment,
        EmailMessage,
    )

    tabelle = {
        "persone": User,
        "clienti": Customer,
        "prodotti": Product,
        "versioni di prodotto": ProductVersion,
        "progetti": Project,
        "documenti": Document,
        "versioni di documento": DocumentVersion,
        "messaggi": EmailMessage,
        "allegati": EmailAttachment,
        "voci di registro": AuditLog,
    }
    return {
        nome: db.scalar(select(func.count()).select_from(classe)) or 0
        for nome, classe in tabelle.items()
    }


# --- Riga di comando ----------------------------------------------------------


def argomenti() -> argparse.Namespace:
    """Legge le opzioni della riga di comando."""
    analizzatore = argparse.ArgumentParser(
        description=(
            "Riempie il database di Aurora con un volume di dati realistico, "
            "per misurare i tempi di risposta delle pagine."
        )
    )
    analizzatore.add_argument("--utenti", type=int, default=UTENTI)
    analizzatore.add_argument("--clienti", type=int, default=CLIENTI)
    analizzatore.add_argument("--prodotti", type=int, default=PRODOTTI)
    analizzatore.add_argument("--versioni", type=int, default=VERSIONI)
    analizzatore.add_argument("--documenti", type=int, default=DOCUMENTI)
    analizzatore.add_argument("--email", type=int, default=MESSAGGI)
    analizzatore.add_argument(
        "--si",
        action="store_true",
        help="non chiede conferma. Per le esecuzioni non presidiate.",
    )
    return analizzatore.parse_args()


def conferma(opzioni: argparse.Namespace) -> bool:
    """Mostra dove si sta per scrivere e chiede il permesso.

    Il database si nomina per esteso, senza la password: chi legge deve poter
    riconoscere **quale** database sta per riempire. E' la stessa precauzione
    di scripts/ripristino.py, in forma piu' leggera - qui non si sovrascrive
    niente, si aggiunge soltanto.
    """
    indirizzo = settings.DATABASE_URL
    if "@" in indirizzo:
        # postgresql+psycopg://utente:password@host/db -> si toglie la
        # password e si tiene tutto il resto, che va letto.
        prima, dopo = indirizzo.split("@", 1)
        schema, _, credenziali = prima.rpartition("://")
        utente = credenziali.split(":", 1)[0]
        indirizzo = f"{schema}://{utente}:***@{dopo}"

    print()
    print("  ATTENZIONE: questo script scrive nel database e non cancella")
    print("  niente. Non va eseguito su un server in esercizio.")
    print()
    print(f"    database: {indirizzo}")
    print(f"    archivio: {settings.storage_dir}")
    print(f"    posta:    {settings.mail_local_dir}")
    print()
    print(
        f"    {opzioni.utenti} persone, {opzioni.clienti} clienti, "
        f"{opzioni.prodotti} prodotti, {opzioni.versioni} versioni,"
    )
    print(f"    {opzioni.documenti} documenti, {opzioni.email} messaggi")
    print()

    if opzioni.si:
        return True

    risposta = input("  Scrivi «procedi» per continuare: ").strip().lower()
    return risposta == "procedi"


def main() -> int:
    """Genera il lotto. Restituisce il codice di uscita del processo."""
    opzioni = argomenti()

    if not conferma(opzioni):
        print("  Annullato: non e' stato scritto niente.")
        return 1

    coda = coda_del_lotto()
    inizio = time.perf_counter()

    print()
    print(f"Generazione del lotto {coda}")
    print()

    db = SessionLocal()
    try:
        autore = primo_creatore(db)
        print(f"  operazioni registrate come: {autore.username}")

        with Passo(f"{opzioni.utenti} persone"):
            persone = crea_le_persone(db, coda, opzioni.utenti)

        with Passo(f"{opzioni.clienti} clienti con i loro contatti"):
            clienti = crea_i_clienti(db, coda, opzioni.clienti, autore)

        with Passo(f"{opzioni.prodotti} prodotti e {opzioni.versioni} versioni"):
            prodotti = crea_i_prodotti(
                db, coda, opzioni.prodotti, opzioni.versioni, clienti, autore
            )

        with Passo("progetti, squadre e avanzamento delle fasi"):
            aperti = apri_i_progetti(db, coda, prodotti, persone, autore)
        print(f"    progetti aperti: {len(aperti)}")

        with Passo(f"{opzioni.documenti} documenti"):
            quanti_documenti = crea_i_documenti(
                db, coda, opzioni.documenti, aperti, persone
            )
        print(f"    documenti creati: {quanti_documenti}")

        with Passo(f"{opzioni.email} messaggi scritti nella cartella"):
            scritti = scrivi_i_messaggi(
                settings.mail_local_dir, coda, opzioni.email, prodotti
            )
        print(f"    file .eml scritti: {scritti}")

        with Passo("acquisizione della posta"):
            print()
            acquisiti = acquisisci_i_messaggi(db, autore, scritti)
            print("   ", end="")
        print(f"    messaggi archiviati: {acquisiti}")

        print()
        print("  Nel database ci sono adesso:")
        for nome, quanti in conta(db).items():
            print(f"    {nome:24} {quanti}")

    finally:
        db.close()

    print()
    print(f"Fatto in {time.perf_counter() - inizio:.0f} secondi.")
    print()
    print("Adesso misura i tempi delle pagine:")
    print("    python scripts/misura_tempi.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
