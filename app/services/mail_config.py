"""La configurazione della posta: che cosa si scrive, come si prova, come sta.

Tre cose, e stanno insieme perche' sono la stessa cosa vista in tre momenti:

  1. **i parametri** - quali sono, che aspetto hanno, che cosa vuol dire
     scriverli storti (`PARAMETRI`, `verifica_forma`);
  2. **la prova** - il pulsante VERIFICA accanto a ogni campo, che prova per
     davvero il collegamento e risponde con una frase (`prova_parametro`);
  3. **la diagnostica** - come sta adesso il collegamento: quando e' stato
     l'ultimo controllo, se l'orologio e' acceso, fra quanto scade il segreto
     dell'applicazione (`diagnostica`, `scadenza_segreto`).

**Perche' la pagina esiste.** I quattro parametri della casella arrivano
dall'ufficio informatico su un foglio, e chi li riceve non ha accesso al server
per scriverli nel `.env`. L'azienda ha chiesto esplicitamente che la
configurazione si possa completare senza toccare file di testo: la pagina
scrive il `.env` da sola, passando da `app/services/env_file.py`, e la regola 8
di CLAUDE.md resta in piedi - la configurazione vive ancora li' dentro, e li'
dentro la va a leggere chi amministra il server (D-081).

**Perche' il pulsante VERIFICA e' su ogni campo e non uno solo in fondo.**
Con un pulsante solo, la risposta a quattro parametri sbagliati e' "non
funziona", e chi la legge non sa da dove cominciare. Con un pulsante per campo,
la risposta e' "l'organizzazione indicata non esiste" oppure "il segreto e'
scaduto": in tutte e due i casi si sa quale riga del foglio andare a
riguardare. Microsoft, per fortuna, ci mette del suo: i codici `AADSTS` dicono
esattamente quale delle tre credenziali ha rifiutato, e `graph_api` li traduce.

**I segreti non si rimostrano.** Il campo del segreto dell'applicazione si
presenta vuoto anche quando un segreto c'e', con scritto accanto che c'e'.
Lasciandolo vuoto non si cancella niente: si conferma quello che c'e' gia'.
Rimostrarlo vorrebbe dire metterlo dentro una pagina HTML, che finisce nella
cronologia del browser e nella memoria di chi guarda alle spalle.
"""

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.config import settings
from app.models import User
from app.services import audit, env_file, mail_scheduler, mail_source
from app.services.graph_api import ClienteGraph, Credenziali, ErroreGraph

logger = logging.getLogger("aurora.posta.configurazione")

# L'operazione registrata quando qualcuno salva la pagina. E' una sola: quello
# che si vuole poter ricostruire fra un anno e' "chi ha cambiato i parametri
# della casella, quando, e quali", non un'operazione per campo.
ACTION_MAIL_CONFIG_UPDATED = "mail_config.updated"

# Il valore scritto nel registro al posto del segreto. Il registro deve dire
# che il segreto e' cambiato, non che cosa e' diventato (e' la stessa regola di
# app/services/configuration.py, che della chiave dei cookie registra
# l'impronta e non il valore).
SEGRETO_NASCOSTO = "(modificato)"

# Da quanti giorni prima della scadenza del segreto si comincia a segnalarlo, e
# con quale evidenza. L'elenco si legge dall'alto: il primo che comprende i
# giorni rimasti vince.
#
#   oltre 30 giorni   non si dice niente: e' rumore
#   da 30 a 15        una nota, cosi' si puo' programmare il rinnovo
#   da 14 a 8         un avviso giallo
#   7 o meno          un avviso rosso, e lo stesso dopo la scadenza
SOGLIE_SCADENZA: tuple[tuple[int, str], ...] = (
    (7, "errore"),
    (14, "attenzione"),
    (30, "informazione"),
)

# Da quanti giorni prima si comincia del tutto. E' il numero chiesto
# dall'azienda ed e' scritto qui una volta sola.
GIORNI_DI_PREAVVISO = 30

# La forma di un identificativo di Azure AD: otto, quattro, quattro, quattro,
# dodici cifre esadecimali. Serve a fermare l'errore piu' frequente - copiare
# nel campo sbagliato, o copiarne meta' - prima ancora di chiamare Microsoft.
FORMA_GUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

# La forma di un indirizzo di posta. Volutamente larga: gli indirizzi veri sono
# piu' strani di qualunque espressione regolare, e qui si vuole solo fermare
# "ufficio tecnico" scritto senza chiocciola.
FORMA_INDIRIZZO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------------------------------------------------------------------------
#  1. I PARAMETRI
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Parametro:
    """Un parametro della posta, come lo vede chi compila la pagina.

    nome        il nome nel file .env, che e' anche il nome del campo;
    etichetta   come si chiama in italiano sulla pagina;
    aiuto       la riga sotto il campo: dove si trova quel valore;
    tipo        testo, segreto, data, numero, scelta, spunta;
    provabile   se ha senso metterci accanto un pulsante VERIFICA. Un numero di
                minuti non si prova collegandosi a Microsoft;
    opzioni     le scelte, per i parametri a tendina.
    """

    nome: str
    etichetta: str
    aiuto: str
    tipo: str = "testo"
    provabile: bool = False
    segnaposto: str = ""
    opzioni: tuple[tuple[str, str], ...] = ()


PARAMETRI: tuple[Parametro, ...] = (
    Parametro(
        nome="MAIL_PROVIDER",
        etichetta="Da dove arriva la posta",
        aiuto=(
            "«Cartella di file» legge i messaggi da una cartella del server ed "
            "e' quello che si usa in collaudo. «Casella aziendale» si collega "
            "a Microsoft 365 e richiede i quattro parametri qui sotto."
        ),
        tipo="scelta",
        opzioni=(
            ("locale", "Cartella di file .eml sul server"),
            ("graph", "Casella aziendale di Microsoft 365"),
        ),
    ),
    Parametro(
        nome="MAIL_TENANT_ID",
        etichetta="Identificativo dell'organizzazione",
        aiuto=(
            "Nel portale Microsoft e' la voce «ID directory (tenant)» nella "
            "scheda della registrazione applicativa. Va bene anche il nome di "
            "dominio dell'azienda."
        ),
        provabile=True,
        segnaposto="00000000-0000-0000-0000-000000000000",
    ),
    Parametro(
        nome="MAIL_CLIENT_ID",
        etichetta="Identificativo dell'applicazione",
        aiuto=(
            "Nel portale Microsoft e' la voce «ID applicazione (client)» della "
            "registrazione creata per Aurora."
        ),
        provabile=True,
        segnaposto="00000000-0000-0000-0000-000000000000",
    ),
    Parametro(
        nome="MAIL_CLIENT_SECRET",
        etichetta="Segreto dell'applicazione",
        aiuto=(
            "Il valore della colonna «Valore» del segreto, non quello della "
            "colonna «ID segreto». Si puo' leggere solo nel momento in cui "
            "viene creato: se e' andato perso, se ne crea un altro."
        ),
        tipo="segreto",
        provabile=True,
    ),
    Parametro(
        nome="MAIL_MAILBOX_ADDRESS",
        etichetta="Indirizzo della casella da leggere",
        aiuto=(
            "L'indirizzo completo della casella su cui arrivano i messaggi da "
            "archiviare. Deve essere una casella vera, non un alias e non un "
            "gruppo."
        ),
        provabile=True,
        segnaposto="ordini@azienda.it",
    ),
    Parametro(
        nome="MAIL_SECRET_EXPIRES_ON",
        etichetta="Scadenza del segreto",
        aiuto=(
            "La data in cui il segreto dell'applicazione smette di funzionare, "
            "scritta come 2027-03-15. Aurora comincia a segnalarla trenta "
            "giorni prima. Se si lascia vuota, la scadenza arrivera' senza "
            "preavviso e la posta smettera' di essere letta."
        ),
        tipo="data",
        segnaposto="2027-03-15",
    ),
    Parametro(
        nome="MAIL_POLL_MINUTES",
        etichetta="Ogni quanti minuti si controlla",
        aiuto=(
            "Ogni quanto Aurora va a vedere se e' arrivata posta nuova. Cinque "
            "minuti e' il valore di partenza; sotto il minuto non si scende."
        ),
        tipo="numero",
    ),
    Parametro(
        nome="MAIL_SCHEDULER_ENABLED",
        etichetta="Controllo automatico acceso",
        aiuto=(
            "Quando e' spento la posta si legge soltanto premendo «Controlla "
            "adesso». Il cambiamento ha effetto al riavvio del programma."
        ),
        tipo="spunta",
    ),
)

# I quattro parametri che servono per collegarsi, in ordine di modulo.
PARAMETRI_DEL_COLLEGAMENTO = (
    "MAIL_TENANT_ID",
    "MAIL_CLIENT_ID",
    "MAIL_CLIENT_SECRET",
    "MAIL_MAILBOX_ADDRESS",
)

# I tre che compongono le credenziali dell'applicazione: si provano tutti e tre
# insieme, perche' Microsoft il gettone lo da' o non lo da'.
PARAMETRI_DELLE_CREDENZIALI = (
    "MAIL_TENANT_ID",
    "MAIL_CLIENT_ID",
    "MAIL_CLIENT_SECRET",
)


def parametro(nome: str) -> Parametro | None:
    """La descrizione di un parametro, oppure None se non ne conosciamo uno."""
    for voce in PARAMETRI:
        if voce.nome == nome:
            return voce
    return None


def valori_correnti() -> dict[str, str]:
    """I valori con cui il programma sta girando adesso, come testo.

    Il segreto non c'e': la pagina non lo rimostra mai. Che ci sia o non ci sia
    lo dice `segreto_impostato()`.
    """
    return {
        "MAIL_PROVIDER": settings.MAIL_PROVIDER,
        "MAIL_TENANT_ID": settings.MAIL_TENANT_ID,
        "MAIL_CLIENT_ID": settings.MAIL_CLIENT_ID,
        "MAIL_CLIENT_SECRET": "",
        "MAIL_MAILBOX_ADDRESS": settings.MAIL_MAILBOX_ADDRESS,
        "MAIL_SECRET_EXPIRES_ON": settings.MAIL_SECRET_EXPIRES_ON,
        "MAIL_POLL_MINUTES": str(settings.MAIL_POLL_MINUTES),
        "MAIL_SCHEDULER_ENABLED": "si" if settings.MAIL_SCHEDULER_ENABLED else "",
    }


def segreto_impostato() -> bool:
    """Vero se un segreto dell'applicazione e' gia' stato scritto."""
    return bool(settings.MAIL_CLIENT_SECRET.strip())


def con_i_valori_veri(scritti: dict[str, str]) -> dict[str, str]:
    """Completa i valori del modulo con quelli che il modulo non porta.

    Ce n'e' uno solo, ed e' il segreto: il campo arriva vuoto quando chi
    compila non lo sta cambiando, e vuoto vuol dire "lascia quello che c'e'",
    non "cancellalo".
    """
    completi = dict(scritti)
    if not (completi.get("MAIL_CLIENT_SECRET") or "").strip():
        completi["MAIL_CLIENT_SECRET"] = settings.MAIL_CLIENT_SECRET
    return completi


def credenziali_da(valori: dict[str, str]) -> Credenziali:
    """Le credenziali corrispondenti a un insieme di valori del modulo."""
    completi = con_i_valori_veri(valori)
    return Credenziali(
        tenant_id=(completi.get("MAIL_TENANT_ID") or "").strip(),
        client_id=(completi.get("MAIL_CLIENT_ID") or "").strip(),
        client_secret=(completi.get("MAIL_CLIENT_SECRET") or "").strip(),
        mailbox=(completi.get("MAIL_MAILBOX_ADDRESS") or "").strip(),
    )


# ---------------------------------------------------------------------------
#  2. LA FORMA DI UN VALORE
# ---------------------------------------------------------------------------


def verifica_forma(nome: str, valore: str) -> str | None:
    """Che cosa c'e' che non va in un valore, guardandolo e basta.

    Restituisce la frase da mostrare, oppure None se il valore va bene. Sono i
    controlli che non hanno bisogno di Microsoft: la forma di un
    identificativo, la chiocciola in un indirizzo, una data scritta all'italiana
    invece che in cifre. Servono a due cose - non far partire una chiamata che
    fallira' di sicuro, e dare una risposta immediata a chi ha copiato il campo
    sbagliato.
    """
    testo = (valore or "").strip()

    if nome == "MAIL_PROVIDER":
        if testo not in ("locale", "graph"):
            return "Scegli da dove Aurora deve prendere i messaggi."
        return None

    if nome in ("MAIL_TENANT_ID", "MAIL_CLIENT_ID"):
        if not testo:
            return None
        if FORMA_GUID.match(testo):
            return None
        if nome == "MAIL_TENANT_ID" and "." in testo and " " not in testo:
            # Il tenant si puo' indicare anche con il dominio dell'azienda.
            return None
        return (
            "Questo valore deve essere l'identificativo lungo con i trattini "
            "(otto cifre, poi tre gruppi da quattro, poi dodici)"
            + (", oppure il dominio dell'azienda." if nome == "MAIL_TENANT_ID" else ".")
        )

    if nome == "MAIL_MAILBOX_ADDRESS":
        if not testo:
            return None
        if not FORMA_INDIRIZZO.match(testo):
            return "Questo deve essere un indirizzo di posta completo."
        return None

    if nome == "MAIL_SECRET_EXPIRES_ON":
        if not testo:
            return None
        try:
            date.fromisoformat(testo)
        except ValueError:
            return (
                "La data va scritta con l'anno davanti: 2027-03-15 per il "
                "quindici marzo 2027."
            )
        return None

    if nome == "MAIL_POLL_MINUTES":
        try:
            minuti = int(testo)
        except ValueError:
            return "Qui va un numero di minuti."
        if minuti < 1:
            return "Il controllo non puo' essere piu' frequente di un minuto."
        if minuti > 1440:
            return "Piu' di un giorno non e' un controllo periodico."
        return None

    return None


def problemi_di_forma(valori: dict[str, str]) -> dict[str, str]:
    """Tutti i problemi di forma di un modulo, campo per campo."""
    problemi = {}
    for voce in PARAMETRI:
        errore = verifica_forma(voce.nome, valori.get(voce.nome, ""))
        if errore:
            problemi[voce.nome] = errore
    return problemi


def mancanti_per_il_collegamento(valori: dict[str, str] | None = None) -> list[str]:
    """I parametri della casella ancora da compilare, in ordine di modulo."""
    completi = con_i_valori_veri(valori if valori is not None else valori_correnti())
    return [
        nome
        for nome in PARAMETRI_DEL_COLLEGAMENTO
        if not (completi.get(nome) or "").strip()
    ]


# ---------------------------------------------------------------------------
#  3. LA PROVA DEL COLLEGAMENTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Esito:
    """La risposta di un pulsante VERIFICA.

    `variante` e' il colore con cui mostrarla e sono le tre di sempre:
    successo, attenzione, errore. `parametro` dice su quale campo si e'
    fermata la prova, che non e' sempre quello su cui si e' premuto: chi prova
    l'indirizzo della casella con un segreto sbagliato deve leggere che il
    problema e' il segreto, non che la casella non esiste.
    """

    riuscita: bool
    messaggio: str
    variante: str = "successo"
    parametro: str | None = None


def nuovo_cliente(credenziali: Credenziali) -> ClienteGraph:
    """Costruisce il cliente con cui si prova il collegamento.

    E' una funzione a se' perche' i test la sostituiscono: cosi' la pagina di
    configurazione - compreso il caso "parametri sbagliati" chiesto dai criteri
    di accettazione - si prova senza casella aziendale e senza rete.
    """
    return ClienteGraph(credenziali)


def prova_parametro(nome: str, valori: dict[str, str]) -> Esito:
    """Prova un parametro per davvero e racconta com'e' andata.

    I parametri che non riguardano il collegamento - ogni quanto si controlla,
    la data di scadenza - si "provano" guardandoli: non c'e' niente da chiedere
    a Microsoft, e rispondere "va bene" a una data scritta bene e' comunque la
    risposta che serve a chi ha premuto.
    """
    problema = verifica_forma(nome, valori.get(nome, ""))
    if problema:
        return Esito(False, problema, variante="errore", parametro=nome)

    if nome not in PARAMETRI_DEL_COLLEGAMENTO:
        return Esito(True, _va_bene_cosi(nome, valori))

    completi = con_i_valori_veri(valori)
    if (valori.get("MAIL_PROVIDER") or settings.MAIL_PROVIDER) != "graph":
        return Esito(
            True,
            "Il valore e' scritto bene. Non e' stato provato il collegamento "
            "perche' Aurora sta leggendo la posta da una cartella: per provarlo "
            "scegli «Casella aziendale di Microsoft 365» qui sopra.",
            variante="attenzione",
        )

    credenziali = credenziali_da(completi)
    mancanti = _mancanti_per_provare(nome, credenziali)
    if mancanti:
        etichette = ", ".join(_etichetta_di(n) for n in mancanti)
        return Esito(
            False,
            f"Per provare questo valore servono anche: {etichette}.",
            variante="attenzione",
            parametro=mancanti[0],
        )

    cliente = nuovo_cliente(credenziali)
    try:
        if nome == "MAIL_MAILBOX_ADDRESS":
            fonte = mail_source.FonteGraph(cliente)
            return Esito(True, fonte.verifica())

        cliente.gettone(rinnova=True)
        return Esito(
            True,
            "Microsoft ha accettato le credenziali dell'applicazione. Prova "
            "adesso l'indirizzo della casella: il permesso di leggerla e' una "
            "cosa a parte.",
        )
    except ErroreGraph as errore:
        logger.warning(
            "Prova del parametro %s non riuscita: %s", nome, errore.tecnico
        )
        return Esito(
            False,
            errore.messaggio,
            variante="errore",
            parametro=errore.parametro or nome,
        )
    finally:
        cliente.chiudi()


def prova_completa(valori: dict[str, str]) -> Esito:
    """Prova tutto il giro: credenziali, casella, cartelle di arrivo.

    E' il pulsante in fondo alla pagina. Fa quello che fara' il controllo
    periodico, meno la lettura dei messaggi: se questo riesce, la posta arriva.
    """
    problemi = problemi_di_forma(valori)
    if problemi:
        primo = next(voce.nome for voce in PARAMETRI if voce.nome in problemi)
        return Esito(False, problemi[primo], variante="errore", parametro=primo)

    if (valori.get("MAIL_PROVIDER") or settings.MAIL_PROVIDER) != "graph":
        return Esito(
            True,
            "Aurora sta leggendo la posta dalla cartella del server: non c'e' "
            "nessun collegamento da provare.",
            variante="attenzione",
        )

    mancanti = mancanti_per_il_collegamento(valori)
    if mancanti:
        etichette = ", ".join(_etichetta_di(nome) for nome in mancanti)
        return Esito(
            False,
            f"Mancano ancora: {etichette}.",
            variante="errore",
            parametro=mancanti[0],
        )

    cliente = nuovo_cliente(credenziali_da(valori))
    try:
        fonte = mail_source.FonteGraph(cliente)
        frase = fonte.verifica()
        return Esito(True, frase + " Aurora e' pronta a leggerla.")
    except ErroreGraph as errore:
        logger.warning("Prova del collegamento non riuscita: %s", errore.tecnico)
        return Esito(
            False,
            errore.messaggio,
            variante="errore",
            parametro=errore.parametro,
        )
    finally:
        cliente.chiudi()


def _mancanti_per_provare(nome: str, credenziali: Credenziali) -> list[str]:
    """Quali altri parametri servono per poter provare questo.

    Le tre credenziali si provano tutte e tre insieme, perche' Microsoft il
    gettone lo da' o non lo da'; l'indirizzo della casella ha bisogno anche di
    quelle, perche' per chiedere di una casella bisogna prima essere entrati.
    """
    vuoti = set(credenziali.mancanti())

    if nome in PARAMETRI_DELLE_CREDENZIALI:
        richiesti = PARAMETRI_DELLE_CREDENZIALI
    else:
        richiesti = PARAMETRI_DEL_COLLEGAMENTO

    return [chiave for chiave in richiesti if chiave in vuoti and chiave != nome]


def _etichetta_di(nome: str) -> str:
    """Il nome in italiano di un parametro, per scriverlo in una frase."""
    voce = parametro(nome)
    return voce.etichetta.lower() if voce else nome


def _va_bene_cosi(nome: str, valori: dict[str, str]) -> str:
    """La frase da dare a un parametro che non si prova collegandosi."""
    if nome == "MAIL_POLL_MINUTES":
        minuti = (valori.get(nome) or "").strip() or str(settings.MAIL_POLL_MINUTES)
        return f"Aurora controllera' la casella ogni {minuti} minuti."

    if nome == "MAIL_SECRET_EXPIRES_ON":
        testo = (valori.get(nome) or "").strip()
        if not testo:
            return (
                "Nessuna scadenza indicata: Aurora non potra' avvisare prima "
                "che il segreto smetta di funzionare."
            )
        scadenza = _scadenza_da(testo)
        return scadenza.messaggio if scadenza else "La data e' scritta bene."

    if nome == "MAIL_PROVIDER":
        if (valori.get(nome) or "") == "graph":
            return "Aurora leggera' la posta dalla casella aziendale."
        return "Aurora leggera' la posta dalla cartella del server."

    return "Il valore e' scritto bene."


# ---------------------------------------------------------------------------
#  4. LA SCADENZA DEL SEGRETO
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Scadenza:
    """Quanto manca alla scadenza del segreto dell'applicazione.

    `da_mostrare` e' falso finche' mancano piu' di trenta giorni: prima di
    allora la scadenza c'e' ma non e' una notizia, e una diagnostica che segnala
    sempre qualcosa e' una diagnostica che nessuno guarda piu'.
    """

    giorno: date
    giorni_mancanti: int
    variante: str
    messaggio: str

    @property
    def scaduto(self) -> bool:
        """Vero quando il giorno e' gia' passato."""
        return self.giorni_mancanti < 0

    @property
    def da_mostrare(self) -> bool:
        """Vero quando vale la pena di dirlo a chi guarda la diagnostica."""
        return self.giorni_mancanti <= GIORNI_DI_PREAVVISO


def _scadenza_da(testo: str, *, oggi: date | None = None) -> Scadenza | None:
    """Compone la scadenza a partire da una data scritta. None se illeggibile."""
    try:
        giorno = date.fromisoformat(testo.strip())
    except ValueError:
        return None

    riferimento = oggi or datetime.now(timezone.utc).date()
    mancanti = (giorno - riferimento).days

    if mancanti < 0:
        return Scadenza(
            giorno=giorno,
            giorni_mancanti=mancanti,
            variante="errore",
            messaggio=(
                f"Il segreto dell'applicazione e' scaduto il "
                f"{giorno.strftime('%d/%m/%Y')}: da quel giorno Aurora non "
                "riesce piu' a leggere la posta. Va creato un segreto nuovo nel "
                "portale Microsoft e riscritto qui."
            ),
        )

    variante = "nessuna"
    for soglia, colore in SOGLIE_SCADENZA:
        if mancanti <= soglia:
            variante = colore
            break

    if mancanti == 0:
        frase = (
            "Il segreto dell'applicazione scade oggi. Appena scade, la posta "
            "smette di arrivare."
        )
    elif mancanti <= 7:
        frase = (
            f"Il segreto dell'applicazione scade fra {mancanti} giorni, il "
            f"{giorno.strftime('%d/%m/%Y')}. Quando scade, la posta smette di "
            "arrivare: il segreto nuovo va chiesto adesso."
        )
    elif mancanti <= GIORNI_DI_PREAVVISO:
        frase = (
            f"Il segreto dell'applicazione scade fra {mancanti} giorni, il "
            f"{giorno.strftime('%d/%m/%Y')}. Conviene chiedere ora all'ufficio "
            "informatico di prepararne uno nuovo."
        )
    else:
        frase = (
            f"Il segreto dell'applicazione scade il "
            f"{giorno.strftime('%d/%m/%Y')}, fra {mancanti} giorni."
        )

    return Scadenza(
        giorno=giorno, giorni_mancanti=mancanti, variante=variante, messaggio=frase
    )


def scadenza_segreto(*, oggi: date | None = None) -> Scadenza | None:
    """La scadenza configurata, oppure None se non ce n'e' una leggibile."""
    testo = (settings.MAIL_SECRET_EXPIRES_ON or "").strip()
    if not testo:
        return None
    return _scadenza_da(testo, oggi=oggi)


# ---------------------------------------------------------------------------
#  5. LA DIAGNOSTICA
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VoceDiagnostica:
    """Una riga del riquadro «Come sta il collegamento».

    `variante` e' vuota quando la riga e' solo un'informazione; quando c'e', e'
    una delle tre di sempre e la riga si colora.
    """

    etichetta: str
    valore: str
    variante: str = ""
    nota: str = ""


def diagnostica(*, oggi: date | None = None) -> list[VoceDiagnostica]:
    """Come sta adesso la lettura della posta, in poche righe leggibili.

    E' quello che si guarda quando qualcuno dice "la posta non arriva piu'", e
    l'ordine delle righe e' l'ordine in cui conviene guardarle: prima da dove
    Aurora sta leggendo, poi se e' configurata, poi se l'orologio gira, poi
    com'e' andata l'ultima volta, e infine la scadenza che fara' smettere tutto
    fra un mese.
    """
    voci: list[VoceDiagnostica] = []

    graph = settings.MAIL_PROVIDER == "graph"
    voci.append(
        VoceDiagnostica(
            etichetta="Da dove arriva la posta",
            valore=(
                f"Casella aziendale: {settings.MAIL_MAILBOX_ADDRESS or 'non indicata'}"
                if graph
                else f"Cartella del server: {settings.mail_local_dir}"
            ),
        )
    )

    if graph:
        mancanti = mancanti_per_il_collegamento()
        if mancanti:
            voci.append(
                VoceDiagnostica(
                    etichetta="Parametri",
                    valore="Mancano: "
                    + ", ".join(_etichetta_di(nome) for nome in mancanti),
                    variante="errore",
                    nota="Finche' mancano, la posta non viene letta.",
                )
            )
        else:
            voci.append(
                VoceDiagnostica(
                    etichetta="Parametri",
                    valore="Tutti compilati",
                    variante="successo",
                )
            )

    voci.append(_voce_orologio())
    voci.append(_voce_ultimo_controllo())

    scadenza = scadenza_segreto(oggi=oggi)
    if graph:
        if scadenza is None:
            voci.append(
                VoceDiagnostica(
                    etichetta="Scadenza del segreto",
                    valore=(
                        "Non indicata"
                        if not settings.MAIL_SECRET_EXPIRES_ON.strip()
                        else "Scritta in un modo che non si riesce a leggere"
                    ),
                    variante="attenzione",
                    nota=(
                        "Senza la data, Aurora non puo' avvisare prima che il "
                        "segreto smetta di funzionare."
                    ),
                )
            )
        else:
            voci.append(
                VoceDiagnostica(
                    etichetta="Scadenza del segreto",
                    valore=scadenza.giorno.strftime("%d/%m/%Y"),
                    variante="" if scadenza.variante == "nessuna" else scadenza.variante,
                    nota=scadenza.messaggio if scadenza.da_mostrare else "",
                )
            )

    return voci


def _voce_orologio() -> VoceDiagnostica:
    """La riga che dice se il controllo periodico sta girando."""
    if mail_scheduler.acceso():
        prossimo = mail_scheduler.prossimo_controllo()
        quando = (
            prossimo.astimezone().strftime("%d/%m/%Y alle %H:%M")
            if prossimo is not None
            else "a breve"
        )
        return VoceDiagnostica(
            etichetta="Controllo automatico",
            valore=f"Acceso, ogni {settings.MAIL_POLL_MINUTES} minuti",
            variante="successo",
            nota=f"Il prossimo controllo e' previsto {quando}.",
        )

    if not settings.MAIL_SCHEDULER_ENABLED:
        return VoceDiagnostica(
            etichetta="Controllo automatico",
            valore="Spento dalla configurazione",
            variante="attenzione",
            nota="La posta si legge soltanto con «Controlla adesso».",
        )

    if settings.MAIL_PROVIDER != "graph":
        return VoceDiagnostica(
            etichetta="Controllo automatico",
            valore="Non serve con la cartella del server",
            nota=(
                "I file li mette una persona, che puo' premere «Controlla "
                "adesso» subito dopo."
            ),
        )

    return VoceDiagnostica(
        etichetta="Controllo automatico",
        valore="Non avviato",
        variante="attenzione",
        nota="Ha effetto dal riavvio del programma.",
    )


def _voce_ultimo_controllo() -> VoceDiagnostica:
    """La riga che dice com'e' andata l'ultima lettura."""
    if mail_scheduler.in_corso():
        return VoceDiagnostica(
            etichetta="Ultimo controllo",
            valore="Un controllo e' in corso proprio adesso",
            variante="informazione",
        )

    ultimo = mail_scheduler.ultimo_controllo()
    if ultimo is None:
        return VoceDiagnostica(
            etichetta="Ultimo controllo",
            valore="Nessuno da quando il programma e' stato acceso",
        )

    quando = ultimo.quando.astimezone().strftime("%d/%m/%Y alle %H:%M")
    return VoceDiagnostica(
        etichetta="Ultimo controllo",
        valore=f"{quando} ({ultimo.origine})",
        variante=ultimo.variante if not ultimo.riuscito else "",
        nota=ultimo.messaggio,
    )


# ---------------------------------------------------------------------------
#  6. IL SALVATAGGIO
# ---------------------------------------------------------------------------

# Il commento da mettere nel .env sopra un parametro aggiunto dalla pagina. Chi
# apre quel file con un editore deve capire che cosa sta guardando anche se non
# ha mai visto Aurora.
COMMENTI_ENV: dict[str, str] = {
    "MAIL_TENANT_ID": "Identificativo dell'organizzazione Microsoft 365.",
    "MAIL_CLIENT_ID": "Identificativo della registrazione applicativa di Aurora.",
    "MAIL_CLIENT_SECRET": (
        "Segreto della registrazione applicativa. E' una password: chi puo'\n"
        "leggere questo file puo' leggere la casella."
    ),
    "MAIL_MAILBOX_ADDRESS": "Indirizzo della casella da cui si leggono i messaggi.",
    "MAIL_SECRET_EXPIRES_ON": (
        "Data di scadenza del segreto, scritta come 2027-03-15. Aurora la\n"
        "segnala nella diagnostica a partire da trenta giorni prima."
    ),
    "MAIL_POLL_MINUTES": "Ogni quanti minuti si controlla la casella.",
    "MAIL_SCHEDULER_ENABLED": "Controllo periodico acceso (true) o spento (false).",
}


def salva(
    db: Session,
    valori: dict[str, str],
    *,
    autore: User,
    request: Request | None = None,
) -> list[str]:
    """Scrive i parametri nel `.env`, li applica subito e lo registra.

    Restituisce l'elenco dei parametri davvero cambiati: se non e' cambiato
    niente non si scrive niente e non si registra niente, per la stessa ragione
    per cui non lo fa `configuration.py` all'avvio - un registro con dentro una
    riga a ogni salvataggio a vuoto e' un registro in cui non si trova piu'
    nulla.

    **I valori si applicano anche all'oggetto `settings` che gira adesso.** Il
    file `.env` si legge una volta sola, all'accensione: senza questa riga, chi
    ha appena scritto i parametri dovrebbe far riavviare il server prima di
    poter premere «Controlla adesso», e la pagina che promette di configurare
    la posta non configurerebbe niente. Il controllo periodico fa eccezione e lo
    dice: quello si accende all'avvio (D-081).
    """
    completi = con_i_valori_veri(valori)
    prima = {
        "MAIL_PROVIDER": settings.MAIL_PROVIDER,
        "MAIL_TENANT_ID": settings.MAIL_TENANT_ID,
        "MAIL_CLIENT_ID": settings.MAIL_CLIENT_ID,
        "MAIL_CLIENT_SECRET": settings.MAIL_CLIENT_SECRET,
        "MAIL_MAILBOX_ADDRESS": settings.MAIL_MAILBOX_ADDRESS,
        "MAIL_SECRET_EXPIRES_ON": settings.MAIL_SECRET_EXPIRES_ON,
        "MAIL_POLL_MINUTES": str(settings.MAIL_POLL_MINUTES),
        "MAIL_SCHEDULER_ENABLED": _booleano(settings.MAIL_SCHEDULER_ENABLED),
    }

    dopo = {
        "MAIL_PROVIDER": (completi.get("MAIL_PROVIDER") or "locale").strip(),
        "MAIL_TENANT_ID": (completi.get("MAIL_TENANT_ID") or "").strip(),
        "MAIL_CLIENT_ID": (completi.get("MAIL_CLIENT_ID") or "").strip(),
        "MAIL_CLIENT_SECRET": (completi.get("MAIL_CLIENT_SECRET") or "").strip(),
        "MAIL_MAILBOX_ADDRESS": (completi.get("MAIL_MAILBOX_ADDRESS") or "").strip(),
        "MAIL_SECRET_EXPIRES_ON": (
            completi.get("MAIL_SECRET_EXPIRES_ON") or ""
        ).strip(),
        "MAIL_POLL_MINUTES": (completi.get("MAIL_POLL_MINUTES") or "5").strip(),
        "MAIL_SCHEDULER_ENABLED": _booleano(
            bool((completi.get("MAIL_SCHEDULER_ENABLED") or "").strip())
        ),
    }

    cambiati = [nome for nome in dopo if dopo[nome] != prima[nome]]
    if not cambiati:
        return []

    env_file.scrivi_parametri(dopo, commenti=COMMENTI_ENV)
    _applica(dopo)

    audit.record(
        db,
        action=ACTION_MAIL_CONFIG_UPDATED,
        entity_type=audit.ENTITY_SISTEMA,
        user_id=autore.id,
        request=request,
        old_value=_da_registrare(prima, cambiati),
        new_value=_da_registrare(dopo, cambiati),
        description=(
            "Configurazione della posta modificata: "
            + ", ".join(_etichetta_di(nome) for nome in cambiati)
        ),
    )

    logger.info("Configurazione della posta modificata: %s", ", ".join(cambiati))
    return cambiati


def _applica(dopo: dict[str, str]) -> None:
    """Porta i valori appena salvati dentro l'oggetto `settings` in memoria."""
    settings.MAIL_PROVIDER = dopo["MAIL_PROVIDER"]  # type: ignore[assignment]
    settings.MAIL_TENANT_ID = dopo["MAIL_TENANT_ID"]
    settings.MAIL_CLIENT_ID = dopo["MAIL_CLIENT_ID"]
    settings.MAIL_CLIENT_SECRET = dopo["MAIL_CLIENT_SECRET"]
    settings.MAIL_MAILBOX_ADDRESS = dopo["MAIL_MAILBOX_ADDRESS"]
    settings.MAIL_SECRET_EXPIRES_ON = dopo["MAIL_SECRET_EXPIRES_ON"]
    settings.MAIL_POLL_MINUTES = int(dopo["MAIL_POLL_MINUTES"] or 5)
    settings.MAIL_SCHEDULER_ENABLED = dopo["MAIL_SCHEDULER_ENABLED"] == "true"


def _booleano(valore: bool) -> str:
    """Come si scrive un booleano nel file .env."""
    return "true" if valore else "false"


def _da_registrare(valori: dict[str, str], cambiati: list[str]) -> dict[str, Any]:
    """I valori da mettere nel registro: solo i cambiati, senza il segreto."""
    riga: dict[str, Any] = {}
    for nome in cambiati:
        if nome == "MAIL_CLIENT_SECRET":
            riga[nome] = SEGRETO_NASCOSTO
        else:
            riga[nome] = valori[nome] or "(vuoto)"
    return riga
