"""La configurazione guidata del primo avvio.

**Il problema che risolve.** Aurora appena installata e' un database vuoto e un
file `.env` da compilare. Fino alla sessione 11 il primo avvio era una
sequenza di comandi da riga di comando - `alembic upgrade head`, `python
scripts/seed.py`, l'editore di testo sul `.env` - documentata bene e comunque
sbagliabile in sei punti. L'azienda ha chiesto che si arrivi a un sistema
utilizzabile **senza toccare nessun file di testo**.

**Come funziona.** Sei passi. Ogni passo spiega in italiano semplice che cosa
si sta facendo e perche', ha un pulsante che verifica e risponde subito, e
quando e' a posto diventa verde.

    1. il database        c'e'? le tabelle ci sono?
    2. il primo utente    chi amministrera' Aurora
    3. l'archivio         dove finiranno i file, e ci si puo' scrivere?
    4. le classificazioni chi vede che cosa
    5. le fasi            il percorso che seguono i progetti
    6. la posta           rimandabile: si puo' fare dopo

**La procedura si puo' interrompere e riprendere**, e non e' costato niente
farlo: **lo stato non e' scritto da nessuna parte, si ricava.** Il passo 2 e'
fatto se esiste un creatore, il 4 se esistono le classificazioni, il 5 se
esiste un modello di fasi. Chiudere il browser a meta' e tornare domani
significa ricalcolare le stesse risposte e ritrovarsi dove si era rimasti.
Una tabella "a che punto sono" avrebbe avuto lo stesso comportamento nel caso
normale e un comportamento sbagliato in quello vero: qualcuno che crea le
classificazioni da un'altra pagina lascerebbe indietro la tabella, e la
procedura direbbe di fare una cosa gia' fatta.

**Chi puo' aprirla.** Finche' non esiste nessun creatore, chiunque: non c'e'
nessuno a cui chiedere il permesso, ed e' esattamente la ragione per cui
`sistema_da_configurare()` non guarda soltanto gli utenti. Un sistema pieno di
documenti in cui qualcuno ha disattivato l'ultimo amministratore **non** e' da
configurare: e' un sistema rotto, e riaprire li' una procedura che crea
amministratori senza credenziali vorrebbe dire regalare le chiavi a chiunque
arrivi al server. Da quando il creatore esiste, la procedura la puo' aprire
solo lui.

**Qui non si decide nessun permesso** (D-051) e non si guarda nessun ruolo:
la domanda "esiste un creatore?" la fa `users.esiste_un_creatore()`, che sta
nel file in cui e' lecito guardare il ruolo globale.
"""

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import PROJECT_ROOT, settings
from app.models import Classification, Document, PhaseTemplate, User
from app.services import (
    diagnostics,
    env_file,
    initial_data,
    mail_config,
    permissions,
    phases,
    users,
)

logger = logging.getLogger("aurora.primo_avvio")

# Una tabella qualunque: o ci sono tutte o non c'e' nessuna. E' la stessa
# sentinella che usano i test (tests/conftest.py), e va bene che sia la stessa:
# se un giorno quella tabella sparisse, meglio accorgersene in tutte e due i
# posti insieme.
TABELLA_SENTINELLA = "product_versions"

# I nomi dei sei passi. Sono identificatori, quindi in inglese come tutto il
# resto del codice; il titolo italiano sta in PASSI qui sotto.
PASSO_DATABASE = "database"
PASSO_CREATORE = "creator"
PASSO_ARCHIVIO = "storage"
PASSO_CLASSIFICAZIONI = "classifications"
PASSO_FASI = "phases"
PASSO_POSTA = "mail"


# ---------------------------------------------------------------------------
#  1. LA FORMA DI UN PASSO E DI UNA VERIFICA
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Verifica:
    """L'esito del pulsante «Verifica» di un passo.

    Ha **la stessa forma di `diagnostics.Voce`** - colore, variante, titolo,
    valore, che_fare, dettagli - e non e' un caso: la disegna lo stesso
    componente (`components/semaforo.html`). Due pagine che mostrano la stessa
    cosa devono riceverla nella stessa forma, altrimenti diventano due cose che
    si somigliano.
    """

    colore: str
    titolo: str
    valore: str
    che_fare: str = ""
    dettagli: tuple[tuple[str, str], ...] = ()
    dove: str = ""

    @property
    def variante(self) -> str:
        """Il colore tradotto nella variante del componente «etichetta»."""
        return diagnostics.VARIANTE_DEL_COLORE[self.colore]

    @property
    def a_posto(self) -> bool:
        """Vero quando il passo si puo' considerare fatto."""
        return self.colore == diagnostics.VERDE


@dataclass(frozen=True)
class Passo:
    """Un passo della procedura, gia' pronto da disegnare.

    numero      la sua posizione, da 1 a 6;
    chiave      il nome interno, quello che finisce nell'indirizzo;
    titolo      come si chiama, in italiano;
    perche      **a che cosa serve**, in una frase che si capisce senza sapere
                che cos'e' un database. E' la parte che rende la procedura una
                guida invece che un modulo lungo;
    fatto       se e' gia' a posto;
    rimandabile se si puo' saltare e farlo dopo (solo la posta).
    """

    numero: int
    chiave: str
    titolo: str
    perche: str
    fatto: bool = False
    rimandabile: bool = False
    dettaglio: str = ""


# I sei passi, nell'ordine in cui vanno affrontati, con la spiegazione che si
# legge sopra ciascuno. L'ordine non e' modificabile dall'interfaccia ed e'
# giusto cosi': non si crea un utente prima di sapere se il database c'e', e
# non si scelgono le classificazioni prima di avere qualcuno che le crei.
PASSI: tuple[tuple[str, str, str, bool], ...] = (
    (
        PASSO_DATABASE,
        "Il database",
        "Aurora conserva tutto - progetti, documenti, persone - dentro un "
        "programma separato che si chiama PostgreSQL. Questo passo controlla "
        "che ci sia, che risponda e che dentro ci siano le tabelle che "
        "servono. Se non e' a posto, gli altri cinque passi non si possono "
        "nemmeno cominciare.",
        False,
    ),
    (
        PASSO_CREATORE,
        "La prima persona",
        "Serve qualcuno che possa amministrare Aurora: creare gli altri "
        "utenti, decidere chi vede che cosa, aprire i progetti. Questa e' la "
        "sola persona che si crea da qui; tutte le altre le creera' lei, "
        "dall'interno del programma.",
        False,
    ),
    (
        PASSO_ARCHIVIO,
        "L'archivio dei file",
        "I documenti caricati - schemi, disegni, distinte, firmware - non "
        "finiscono nel database: finiscono in una cartella sul disco. Qui si "
        "sceglie quale, e si verifica che Aurora ci possa scrivere davvero. "
        "Conviene un disco diverso da quello del sistema, e conviene che sia "
        "una cartella compresa nelle copie di sicurezza del server.",
        False,
    ),
    (
        PASSO_CLASSIFICAZIONI,
        "Le classificazioni",
        "Ogni documento caricato in Aurora ha una classificazione - Tecnico, "
        "Commerciale, Qualita', Amministrativo, Corrispondenza - ed e' la "
        "classificazione a decidere chi lo puo' vedere. Qui si creano quelle "
        "di partenza, con la griglia dei permessi gia' compilata in modo "
        "ragionevole: si cambia tutto dopo, dalla pagina «Permessi».",
        False,
    ),
    (
        PASSO_FASI,
        "Il percorso dei progetti",
        "Un progetto in Aurora attraversa delle fasi, in ordine: dall'idea "
        "alla consegna. Le fasi non sono scritte dentro il programma, sono "
        "dati che si scelgono qui e si cambiano quando serve. Questo passo "
        "crea il percorso di partenza, con sei fasi.",
        False,
    ),
    (
        PASSO_POSTA,
        "La casella di posta",
        "Aurora puo' archiviare da sola la corrispondenza con i clienti, "
        "leggendola da una casella aziendale di Microsoft 365. Servono quattro "
        "parametri che li fornisce l'ufficio informatico, e quasi mai si hanno "
        "il primo giorno: questo passo si puo' rimandare, e il programma "
        "funziona lo stesso in tutto il resto.",
        True,
    ),
)


# ---------------------------------------------------------------------------
#  2. IL SISTEMA E' DA CONFIGURARE?
# ---------------------------------------------------------------------------


def sistema_da_configurare(db: Session) -> bool:
    """Dice se la procedura guidata si deve aprire a chi non e' entrato.

    **Due condizioni, e servono tutte e due.**

    La prima e' che non esista nessun creatore attivo: e' quella ovvia, ed e'
    quella che si verifica su un'installazione appena fatta.

    La seconda e' che non ci sia nessun documento. Sembra ridondante e non lo
    e': senza, un sistema in uso da due anni in cui qualcuno ha disattivato
    per sbaglio l'ultimo amministratore riaprirebbe a chiunque arrivi al
    server una pagina che crea amministratori senza chiedere credenziali. Con
    la seconda condizione, quel sistema resta chiuso e il rimedio e'
    `python scripts/reimposta_password.py`, che si esegue **dal server** - cioe'
    da chi ci puo' gia' entrare.

    **Se il database non risponde, la risposta e' si'.** Un database che non
    c'e' e' indistinguibile da un database vuoto per chi guarda da fuori, e in
    tutti e due i casi il posto giusto in cui mandare una persona e' il primo
    passo della procedura, che glielo spiega. La sessione va annullata prima di
    proseguire, altrimenti resterebbe rotta per tutte le interrogazioni
    successive.
    """
    try:
        if users.esiste_un_creatore(db):
            return False

        documenti = db.scalar(select(func.count()).select_from(Document)) or 0
        return documenti == 0
    except SQLAlchemyError as errore:
        db.rollback()
        logger.info(
            "Il database non risponde alla domanda «e' gia' configurato?» "
            "(%s): si apre la configurazione guidata",
            errore,
        )
        return True


def procedura_completata(db: Session) -> bool:
    """Vero quando i cinque passi obbligatori sono tutti a posto.

    La posta non conta: e' rimandabile per costruzione, e un sistema senza
    casella aziendale e' un sistema che funziona.
    """
    stato = stato_dei_passi(db)
    return all(passo.fatto for passo in stato if passo.chiave != PASSO_POSTA)


# ---------------------------------------------------------------------------
#  3. A CHE PUNTO SIAMO
# ---------------------------------------------------------------------------


def stato_dei_passi(db: Session) -> list[Passo]:
    """I sei passi con, per ciascuno, se e' gia' a posto.

    **Non legge nessuno stato salvato: lo ricava ogni volta.** E' quello che
    rende la procedura interrompibile senza aver scritto una riga di codice per
    renderla tale.
    """
    fatti = _che_cosa_c_e_gia(db)

    passi: list[Passo] = []
    for numero, (chiave, titolo, perche, rimandabile) in enumerate(PASSI, start=1):
        passi.append(
            Passo(
                numero=numero,
                chiave=chiave,
                titolo=titolo,
                perche=perche,
                fatto=fatti[chiave][0],
                dettaglio=fatti[chiave][1],
                rimandabile=rimandabile,
            )
        )
    return passi


def _che_cosa_c_e_gia(db: Session) -> dict[str, tuple[bool, str]]:
    """Per ogni passo: e' fatto, e in una riga che cosa c'e'.

    Se il database non risponde, il primo passo e' l'unico che sa dire
    qualcosa e tutti gli altri risultano da fare: e' la verita', non un
    ripiego.
    """
    vuoto = {chiave: (False, "") for chiave, _t, _p, _r in PASSI}

    tabelle = _tabelle_presenti(db)
    if not tabelle:
        vuoto[PASSO_DATABASE] = (False, "Il database non risponde o e' vuoto.")
        vuoto[PASSO_ARCHIVIO] = _stato_archivio()
        return vuoto

    vuoto[PASSO_DATABASE] = (True, f"{len(tabelle)} tabelle al loro posto.")

    try:
        creatori = (
            db.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True)))
            or 0
        )
        classificazioni = (
            db.scalar(
                select(func.count())
                .select_from(Classification)
                .where(Classification.is_active.is_(True))
            )
            or 0
        )
        modelli = (
            db.scalar(
                select(func.count())
                .select_from(PhaseTemplate)
                .where(PhaseTemplate.is_active.is_(True))
            )
            or 0
        )
        c_e_un_creatore = users.esiste_un_creatore(db)
    except SQLAlchemyError as errore:
        db.rollback()
        logger.error("Primo avvio: il database ha smesso di rispondere (%s)", errore)
        vuoto[PASSO_DATABASE] = (False, "Il database ha smesso di rispondere.")
        return vuoto

    vuoto[PASSO_CREATORE] = (
        c_e_un_creatore,
        f"{creatori} persone possono entrare." if creatori else "",
    )
    vuoto[PASSO_ARCHIVIO] = _stato_archivio()
    vuoto[PASSO_CLASSIFICAZIONI] = (
        classificazioni > 0,
        f"{classificazioni} classificazioni attive." if classificazioni else "",
    )
    vuoto[PASSO_FASI] = (
        modelli > 0,
        f"{modelli} modelli di fasi attivi." if modelli else "",
    )
    vuoto[PASSO_POSTA] = _stato_posta()

    return vuoto


def _tabelle_presenti(db: Session) -> list[str]:
    """I nomi delle tabelle del database. Elenco vuoto se non si riesce a leggerle."""
    try:
        db.execute(text("select 1"))
        return list(inspect(db.get_bind()).get_table_names())
    except SQLAlchemyError as errore:
        db.rollback()
        logger.info("Primo avvio: le tabelle non si leggono (%s)", errore)
        return []


def _stato_archivio() -> tuple[bool, str]:
    """L'archivio: esiste ed e' scrivibile?"""
    esito = prova_archivio(str(settings.STORAGE_PATH))
    return esito.a_posto, str(settings.storage_dir)


def _stato_posta() -> tuple[bool, str]:
    """La posta: e' configurata? Con la cartella locale si', per definizione."""
    if settings.MAIL_PROVIDER != "graph":
        return True, "I messaggi si leggono da una cartella del server."

    mancanti = mail_config.mancanti_per_il_collegamento()
    if mancanti:
        return False, f"Mancano {len(mancanti)} parametri della casella."
    return True, f"Casella {settings.MAIL_MAILBOX_ADDRESS}."


# ---------------------------------------------------------------------------
#  4. IL PASSO 1: IL DATABASE
# ---------------------------------------------------------------------------


def prova_database(db: Session) -> Verifica:
    """Il database risponde, e le tabelle ci sono?

    Sono due guasti diversi con due rimedi diversi, e questa funzione li
    distingue apposta: PostgreSQL spento si risolve avviando un servizio di
    Windows, le tabelle mancanti si risolvono con un comando. Dire "il
    database non va" in tutti e due i casi vorrebbe dire far provare a caso.
    """
    try:
        db.execute(text("select 1"))
    except SQLAlchemyError as errore:
        db.rollback()
        return Verifica(
            colore=diagnostics.ROSSO,
            titolo="Il database",
            valore="PostgreSQL non risponde",
            che_fare=diagnostics.CHE_FARE_DATABASE,
            dettagli=(("Errore tecnico", f"{type(errore).__name__}"),),
        )

    tabelle = _tabelle_presenti(db)

    if TABELLA_SENTINELLA not in tabelle:
        return Verifica(
            colore=diagnostics.ROSSO,
            titolo="Il database",
            valore="PostgreSQL risponde, ma le tabelle di Aurora non ci sono",
            che_fare=(
                "Il database c'e' ed e' vuoto: mancano le tabelle. Si creano "
                "con un comando solo, dal server, dentro la cartella di "
                "Aurora e con l'ambiente virtuale attivo:\n\n"
                "    .venv\\Scripts\\activate\n"
                "    alembic upgrade head\n\n"
                "Poi torna qui e premi «Verifica» di nuovo."
            ),
            dettagli=(("Tabelle trovate", str(len(tabelle))),),
        )

    return Verifica(
        colore=diagnostics.VERDE,
        titolo="Il database",
        valore=f"PostgreSQL risponde e ha le {len(tabelle)} tabelle di Aurora",
        dettagli=(
            ("Tabelle", str(len(tabelle))),
            ("Collegamento", _database_senza_password()),
        ),
    )


def _database_senza_password() -> str:
    """La stringa di collegamento senza la password, per mostrarla.

    Chi guarda questa pagina ha bisogno di sapere **a quale** database Aurora
    si sta collegando - sbagliare server e' l'errore piu' facile di tutti - e
    non ha nessun bisogno di rileggere la password sullo schermo.
    """
    url = settings.DATABASE_URL
    if "@" not in url:
        return url

    prima, dopo = url.rsplit("@", 1)
    if ":" in prima and "//" in prima:
        inizio, credenziali = prima.split("//", 1)
        utente = credenziali.split(":", 1)[0]
        return f"{inizio}//{utente}:***@{dopo}"
    return f"{prima}@{dopo}"


# ---------------------------------------------------------------------------
#  5. IL PASSO 3: L'ARCHIVIO
# ---------------------------------------------------------------------------

# Il nome del file di prova che si scrive per verificare i permessi. Comincia
# con un punto e dice da solo che cosa e': se qualcuno lo trova, sa perche' c'e'.
FILE_DI_PROVA = ".aurora-prova-scrittura"


def prova_archivio(percorso_scritto: str) -> Verifica:
    """Verifica che nella cartella indicata Aurora possa davvero scrivere.

    **Non basta guardare i permessi, bisogna provare a scrivere.** Su Windows i
    permessi effettivi di una cartella dipendono da ereditarieta', gruppi e
    condivisioni di rete, e l'unico modo affidabile di sapere se un programma
    ci puo' scrivere e' fargli scrivere un file. Lo si scrive, lo si rilegge e
    lo si toglie: e' l'unica cancellazione di file che Aurora esegue, e non
    contraddice la regola 5 di CLAUDE.md perche' quel file non e' un dato
    dell'azienda - e' un file che abbiamo appena inventato noi per provare.

    **La cartella viene creata se non c'e'.** Chi sta configurando ha appena
    scritto un percorso: pretendere che vada a crearlo con Esplora risorse e
    poi torni qui sarebbe esattamente il genere di andirivieni che questa
    procedura esiste per togliere.
    """
    scritto = (percorso_scritto or "").strip()
    if not scritto:
        return Verifica(
            colore=diagnostics.ROSSO,
            titolo="L'archivio dei file",
            valore="Non e' stato indicato nessun percorso",
            che_fare=(
                "Scrivi la cartella in cui Aurora dovra' depositare i "
                "documenti. Puo' essere un percorso assoluto "
                "(D:\\AuroraArchivio) oppure relativo alla cartella del "
                "programma (storage)."
            ),
        )

    percorso = Path(scritto)
    if not percorso.is_absolute():
        percorso = PROJECT_ROOT / percorso

    try:
        percorso.mkdir(parents=True, exist_ok=True)
    except OSError as errore:
        return Verifica(
            colore=diagnostics.ROSSO,
            titolo="L'archivio dei file",
            valore="La cartella non si riesce a creare",
            che_fare=(
                f"Aurora non e' riuscita a creare la cartella {percorso}. "
                "Controlla che il disco esista e sia collegato, che il "
                "percorso sia scritto bene e che l'utente di Windows con cui "
                "gira Aurora abbia il permesso di scrivere li' dentro."
            ),
            dettagli=(("Errore", str(errore)),),
        )

    prova = percorso / FILE_DI_PROVA
    try:
        prova.write_bytes(b"Aurora: prova di scrittura. Si puo' cancellare.")
        riletto = prova.read_bytes()
        if not riletto:
            raise OSError("il file riletto e' vuoto")
    except OSError as errore:
        return Verifica(
            colore=diagnostics.ROSSO,
            titolo="L'archivio dei file",
            valore="La cartella c'e', ma Aurora non ci puo' scrivere",
            che_fare=(
                f"La cartella {percorso} esiste, ma il tentativo di scriverci "
                "dentro un file e' fallito. Sul server, apri le proprieta' di "
                "quella cartella, scheda «Sicurezza», e dai il controllo "
                "completo all'utente di Windows con cui gira Aurora. Se la "
                "cartella e' su una condivisione di rete, i permessi vanno "
                "dati anche sulla condivisione."
            ),
            dettagli=(("Errore", str(errore)),),
        )
    finally:
        # Il file di prova non serve piu' e non deve restare li' a confondere
        # chi guarda l'archivio.
        try:
            prova.unlink(missing_ok=True)
        except OSError:
            logger.warning("Non si e' riuscito a togliere %s", prova)

    try:
        uso = shutil.disk_usage(percorso)
        spazio = (
            f"{diagnostics.misura(uso.free)} liberi su "
            f"{diagnostics.misura(uso.total)}"
        )
    except OSError:
        spazio = "non misurabile"

    gia_dentro, quanti = diagnostics.spazio_occupato(percorso)

    return Verifica(
        colore=diagnostics.VERDE,
        titolo="L'archivio dei file",
        valore="La cartella c'e' e Aurora ci puo' scrivere",
        dettagli=(
            ("Cartella", str(percorso)),
            ("Spazio sul disco", spazio),
            (
                "Gia' presenti",
                f"{quanti} file, {diagnostics.misura(gia_dentro)}"
                if quanti
                else "niente: la cartella e' vuota",
            ),
        ),
    )


def salva_archivio(percorso_scritto: str) -> Path:
    """Scrive STORAGE_PATH nel file `.env` e lo applica subito.

    Passa da `env_file.scrivi_parametri()`, che e' l'unico posto del programma
    che tocca quel file (D-081): riscrive **solo** quella riga e lascia stare
    i commenti, che sono la sola documentazione che chi amministra il server
    abbia sottomano.
    """
    pulito = (percorso_scritto or "").strip()

    env_file.scrivi_parametri(
        {"STORAGE_PATH": pulito},
        commenti={
            "STORAGE_PATH": (
                "Cartella in cui Aurora deposita i documenti caricati.\n"
                "Scritta dalla configurazione guidata del primo avvio."
            )
        },
    )

    settings.STORAGE_PATH = Path(pulito)
    settings.storage_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Primo avvio: archivio impostato su %s", settings.storage_dir)
    return settings.storage_dir


# ---------------------------------------------------------------------------
#  6. IL PASSO 4: LE CLASSIFICAZIONI
# ---------------------------------------------------------------------------
#
# **Gli elenchi non stanno qui.** Le classificazioni, la griglia dei permessi e
# le fasi di partenza si leggono da `config/dati_iniziali.toml`, e li legge
# `app/services/initial_data.py`. Ci stanno per la regola 8 di CLAUDE.md - e'
# roba che l'azienda potrebbe cambiare - e per una seconda ragione che riguarda
# solo le fasi: in Aurora le fasi sono **dati e non codice** (D-055), e c'e' un
# test che legge i sorgenti e diventa rosso se un nome di fase ricompare dentro
# `app/`. Scriverli qui li avrebbe rimessi esattamente dove non devono stare.
#
# Ne discende anche che chi installa dalla riga di comando
# (`scripts/seed.py`) e chi installa dall'interfaccia leggono **lo stesso
# file**, quindi ottengono lo stesso sistema. Prima della sessione 12 erano due
# elenchi scritti in due posti, e bastava correggerne uno.


def crea_classificazioni_di_partenza(
    db: Session, *, autore: User, request: Any = None
) -> list[str]:
    """Crea le classificazioni che mancano, con la loro griglia di permessi.

    Restituisce i nomi di quelle create adesso: l'elenco vuoto vuol dire che
    c'erano gia' tutte, e la pagina lo dice invece di far credere di aver
    lavorato.

    **E' ripetibile senza fare danni.** Ogni classificazione viene cercata per
    nome prima di essere creata, e le caselle gia' presenti non si toccano: chi
    avesse gia' corretto la griglia dalla pagina «Permessi» non se la vede
    riportare indietro.

    Passa da `permissions.crea_classificazione()`, che e' la funzione che
    l'interfaccia usa gia': cosi' nascono anche qui con tutte e tre le caselle
    della matrice, e con la loro riga nel registro.
    """
    iniziali = initial_data.dati()
    create: list[str] = []

    for classe in iniziali.classificazioni:
        gia_c_e = db.scalar(
            select(Classification).where(Classification.name == classe.nome)
        )
        if gia_c_e is not None:
            continue

        permissions.crea_classificazione(
            db,
            nome=classe.nome,
            descrizione=classe.descrizione,
            autore=autore,
            request=request,
        )
        create.append(classe.nome)

    if create:
        _applica_griglia_di_partenza(db, autore=autore, request=request)

    return create


def _applica_griglia_di_partenza(
    db: Session, *, autore: User, request: Any = None
) -> None:
    """Mette nella griglia i permessi di partenza.

    Le classificazioni nascono con i permessi tutti chiusi (e' la scelta
    prudente di `crea_classificazione`): qui si aprono quelli che l'azienda ha
    chiesto. Passa da `permissions.confronta_matrice()` e
    `permissions.salva_matrice()`, che sono la stessa strada della pagina
    «Permessi», quindi ogni casella cambiata finisce nel registro esattamente
    come se qualcuno l'avesse spuntata a mano.
    """
    voluti = initial_data.dati().caselle()
    if not voluti:
        return

    # Le scelte hanno la forma che arriva dal modulo della pagina «Permessi»:
    # "ruolo:identificativo:colonna" -> vero/falso.
    scelte: dict[str, bool] = {}
    for casella in permissions.matrice(db):
        spunte = voluti.get(
            (casella.project_role.value, casella.classificazione.name)
        )
        if spunte is None:
            continue
        for (_nel_file, colonna), valore in zip(initial_data.PERMESSI, spunte):
            scelte[f"{casella.nome_campo}:{colonna}"] = valore

    cambiamenti = permissions.confronta_matrice(db, scelte)
    permissions.salva_matrice(db, cambiamenti, autore, request)


# ---------------------------------------------------------------------------
#  7. IL PASSO 5: IL PERCORSO DELLE FASI
# ---------------------------------------------------------------------------


def crea_percorso_di_partenza(
    db: Session, *, autore: User, request: Any = None
) -> PhaseTemplate | None:
    """Crea il modello di fasi di partenza, se non c'e' gia'.

    Restituisce il modello creato, oppure None se ne esisteva gia' uno con quel
    nome o se il file dei dati iniziali non si e' potuto leggere. Passa da
    `phases.crea_modello()`, che e' la funzione che usa la pagina «Fasi»:
    stesso risultato, stessa riga nel registro.

    **Il nome del modello e i nomi delle fasi arrivano dal file**, e non da
    qui: e' quello che tiene in piedi D-055 anche per i dati iniziali.
    """
    iniziali = initial_data.dati()
    if not iniziali.leggibili or not iniziali.fasi:
        return None

    if phases.nome_gia_usato(db, iniziali.modello_fasi):
        return None

    fasi = [
        phases.FaseScritta(
            nome=fase.nome,
            descrizione=fase.descrizione,
            blocca_ritorno=fase.blocca_ritorno,
            chiude_progetto=fase.chiude_progetto,
        )
        for fase in iniziali.fasi
    ]

    return phases.crea_modello(
        db,
        nome=iniziali.modello_fasi,
        descrizione=iniziali.descrizione_modello,
        norme=[],
        fasi=fasi,
        autore=autore,
        request=request,
    )


# ---------------------------------------------------------------------------
#  8. LA VERIFICA DEI PASSI CHE NON HANNO UNA PROVA PROPRIA
# ---------------------------------------------------------------------------


def prova_passo(db: Session, chiave: str, **valori: str) -> Verifica:
    """La verifica di un passo qualunque, scelta per nome.

    Serve alla rotta, che riceve la chiave del passo dal modulo e non deve
    contenere una catena di `if`: quella catena sta qui, dove si prova.
    """
    if chiave == PASSO_DATABASE:
        return prova_database(db)

    if chiave == PASSO_ARCHIVIO:
        return prova_archivio(valori.get("percorso", str(settings.STORAGE_PATH)))

    if chiave == PASSO_CREATORE:
        return _prova_creatore(db)

    if chiave == PASSO_CLASSIFICAZIONI:
        return _prova_classificazioni(db)

    if chiave == PASSO_FASI:
        return _prova_fasi(db)

    if chiave == PASSO_POSTA:
        return _prova_posta()

    return Verifica(
        colore=diagnostics.GIALLO,
        titolo="Passo sconosciuto",
        valore=f"Non esiste nessun passo chiamato «{chiave}»",
        che_fare="Torna all'elenco dei passi e ricomincia da li'.",
    )


def _prova_creatore(db: Session) -> Verifica:
    """C'e' qualcuno che puo' amministrare Aurora?"""
    if not users.esiste_un_creatore(db):
        return Verifica(
            colore=diagnostics.ROSSO,
            titolo="La prima persona",
            valore="Non c'e' ancora nessuno che possa amministrare Aurora",
            che_fare=(
                "Compila il modulo qui sotto. Servono nome, cognome, "
                "indirizzo di posta e una password: sara' la persona con cui "
                "entrerai per creare tutte le altre."
            ),
        )

    quanti = (
        db.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True)))
        or 0
    )
    return Verifica(
        colore=diagnostics.VERDE,
        titolo="La prima persona",
        valore="C'e' chi puo' amministrare Aurora",
        dettagli=(("Persone che possono entrare", str(quanti)),),
        dove="/utenti",
    )


def _prova_classificazioni(db: Session) -> Verifica:
    """Ci sono le classificazioni con la loro griglia di permessi?"""
    attive = list(
        db.scalars(
            select(Classification).where(Classification.is_active.is_(True))
        ).all()
    )

    if not attive:
        iniziali = initial_data.dati()
        if not iniziali.leggibili:
            # Il file dei dati iniziali non c'e' o e' scritto male. Non e' un
            # motivo per fermarsi: le stesse classificazioni si creano a mano,
            # e l'istruzione dice come (D-039).
            return Verifica(
                colore=diagnostics.ROSSO,
                titolo="Le classificazioni",
                valore="Non ce n'e' nessuna, e non si possono creare da qui",
                che_fare=(
                    f"{iniziali.problema} Senza quel file il pulsante qui "
                    "sotto non ha niente da creare, ma le classificazioni si "
                    "fanno lo stesso a mano dalla pagina «Permessi»: ne serve "
                    "almeno una perche' si possa caricare un documento."
                ),
                dove="/permessi",
            )

        return Verifica(
            colore=diagnostics.ROSSO,
            titolo="Le classificazioni",
            valore="Non ce n'e' nessuna",
            che_fare=(
                "Senza classificazioni non si puo' caricare nessun documento: "
                "e' la classificazione a dire chi lo puo' vedere. Premi il "
                "pulsante qui sotto per creare quelle di partenza."
            ),
        )

    caselle = len(permissions.matrice(db))
    return Verifica(
        colore=diagnostics.VERDE,
        titolo="Le classificazioni",
        valore=f"Ce ne sono {len(attive)}, con {caselle} caselle di permessi",
        dettagli=tuple(
            (classe.name, classe.description or "senza descrizione")
            for classe in attive
        ),
        dove="/permessi",
    )


def _prova_fasi(db: Session) -> Verifica:
    """C'e' almeno un percorso che i progetti possano seguire?"""
    modelli = phases.modelli_di_fasi(db)

    if not modelli:
        iniziali = initial_data.dati()
        if not iniziali.leggibili:
            return Verifica(
                colore=diagnostics.ROSSO,
                titolo="Il percorso dei progetti",
                valore="Non ce n'e' nessuno, e non si puo' crearlo da qui",
                che_fare=(
                    f"{iniziali.problema} Senza quel file il pulsante qui "
                    "sotto non ha niente da creare, ma il percorso si scrive "
                    "lo stesso dalla pagina «Fasi»: e' un modulo con una riga "
                    "per fase, e ne serve almeno uno perche' si possa aprire "
                    "un progetto."
                ),
                dove="/fasi",
            )

        return Verifica(
            colore=diagnostics.ROSSO,
            titolo="Il percorso dei progetti",
            valore="Non c'e' nessun percorso",
            che_fare=(
                "Senza un percorso non si puo' aprire nessun progetto: le "
                "fasi sono l'ossatura su cui si appoggia tutto il resto. "
                f"Premi il pulsante qui sotto per creare quello di partenza, "
                f"con {len(iniziali.fasi)} fasi. Si cambia dopo, dalla pagina "
                "«Fasi»."
            ),
        )

    primo = modelli[0]
    fasi = phases.fasi_del_modello(db, primo.id)
    return Verifica(
        colore=diagnostics.VERDE,
        titolo="Il percorso dei progetti",
        valore=f"C'e' «{primo.name}» con {len(fasi)} fasi",
        dettagli=tuple(
            (f"Fase {numero}", fase.name) for numero, fase in enumerate(fasi, start=1)
        ),
        dove="/fasi",
    )


def _prova_posta() -> Verifica:
    """La posta e' configurata, oppure e' stata legittimamente rimandata?"""
    if settings.MAIL_PROVIDER != "graph":
        return Verifica(
            colore=diagnostics.VERDE,
            titolo="La casella di posta",
            valore="I messaggi si leggono da una cartella del server",
            dettagli=(("Cartella", str(settings.mail_local_dir)),),
            che_fare=(
                "Va benissimo per cominciare: Aurora funziona in tutto il "
                "resto. Quando l'ufficio informatico avra' preparato la "
                "casella aziendale, i quattro parametri si scrivono nella "
                "pagina «Configurazione posta», senza toccare nessun file."
            ),
            dove="/posta/configurazione",
        )

    mancanti = mail_config.mancanti_per_il_collegamento()
    if mancanti:
        return Verifica(
            colore=diagnostics.GIALLO,
            titolo="La casella di posta",
            valore=f"Mancano {len(mancanti)} parametri",
            che_fare=(
                "Questo passo si puo' rimandare: Aurora funziona lo stesso, "
                "e la corrispondenza si archiviera' quando la casella sara' "
                "pronta. I parametri li fornisce l'ufficio informatico: la "
                "richiesta gia' scritta da mandargli e' nel file "
                "docs/RICHIESTA_IT.md."
            ),
            dove="/posta/configurazione",
        )

    return Verifica(
        colore=diagnostics.VERDE,
        titolo="La casella di posta",
        valore=f"Collegata a {settings.MAIL_MAILBOX_ADDRESS}",
        dove="/posta/configurazione",
    )


# ---------------------------------------------------------------------------
#  9. IL NOME UTENTE PROPOSTO
# ---------------------------------------------------------------------------


def username_proposto(db: Session, nome: str, cognome: str) -> str:
    """Il nome utente che Aurora propone per la prima persona.

    E' la stessa funzione che usa la gestione utenti: chi installa e chi
    amministra devono ottenere nomi utente della stessa forma, altrimenti il
    primo utente del sistema e' l'unico diverso da tutti gli altri.
    """
    try:
        return users.proponi_username(db, nome, cognome)
    except SQLAlchemyError:
        db.rollback()
        return ""


# Il file di prova dell'archivio, quando serve toglierlo da fuori.
def pulisci_prova(percorso: Path) -> None:
    """Toglie il file di prova rimasto, se c'e'. Non solleva mai."""
    try:
        (percorso / FILE_DI_PROVA).unlink(missing_ok=True)
    except OSError:
        logger.warning("Non si e' riuscito a togliere il file di prova in %s", percorso)
