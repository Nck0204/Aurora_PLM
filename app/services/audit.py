"""Scrittura nel registro delle operazioni (audit trail).

La tabella audit_logs esiste dalla sessione 2; questa e' la funzione che ci
scrive dentro, ed e' l'unica. Il motivo per cui e' una sola sta in
docs/DECISIONI.md, D-018: la colonna entity_id non ha chiave esterna, quindi
l'integrita' del registro non la garantisce il database ma il codice che lo
riempie. Un codice solo si controlla; venti sparsi per il programma no.

Regola 6 di CLAUDE.md: ogni operazione significativa finisce qui, e ogni riga
dice sempre chi, che cosa, su quale oggetto, quando e da quale indirizzo IP.

I nomi delle azioni sono in inglese e in forma "oggetto.verbo", come vuole
docs/MODELLO_DATI.md: sono identificatori, non testo mostrato.


CHE COSA HA AGGIUNTO LA SESSIONE 9
-----------------------------------

Tre cose, e sono tutte qui dentro.

**Il catalogo.** Ogni azione registrabile ha una riga in CATALOGO, con la sua
frase italiana e il gruppo a cui appartiene. Prima le costanti ACTION_* erano
sparse nei servizi che le usavano, e nessuno poteva rispondere alla domanda
"quali operazioni vengono registrate?" senza leggere tutto il programma.
Adesso la risposta e' un dizionario, la pagina di consultazione ci costruisce
sopra il menu dei filtri, e c'e' un test che verifica che ogni costante del
programma abbia la sua riga qui (tests/test_registro.py).

**La descrizione.** Ogni voce porta con se' una frase in italiano che si
capisce senza conoscere il programma. La compone descrizione_predefinita() al
momento della scrittura e non si ricalcola mai: se domani un documento cambia
titolo, la riga del registro continua a dire come si chiamava quel giorno. E'
il motivo per cui la descrizione e' una colonna e non una funzione di
visualizzazione.

**La catena.** Ogni voce contiene l'impronta SHA-256 della voce precedente.
Non impedisce a chi amministra il database di correggere una riga - contro
quello non esiste difesa dentro il database stesso - ma rende la correzione
**visibile**: da quella riga in poi le impronte non tornano piu', e
scripts/verifica_audit.py lo dice. Vedi D-063.
"""

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import Request
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.models import AuditLog

logger = logging.getLogger("aurora.audit")


# ---------------------------------------------------------------------------
#  1. I NOMI DELLE AZIONI
# ---------------------------------------------------------------------------
#
# Le costanti dell'accesso e della gestione utenti stanno qui perche' qui sono
# nate. Quelle degli altri argomenti stanno nel servizio che le usa
# (documents.py, products.py, phases.py...): spostarle tutte avrebbe voluto
# dire toccare quaranta chiamate senza guadagnare niente. Quello che conta e'
# che **tutte**, comprese quelle degli altri file, abbiano la loro riga in
# CATALOGO qui sotto, e c'e' un test che lo verifica leggendo i sorgenti.

# Accesso e sessioni
ACTION_LOGIN = "user.login"
ACTION_LOGIN_FAILED = "user.login_failed"
ACTION_LOGIN_BLOCKED = "user.login_blocked"
ACTION_LOGOUT = "user.logout"
ACTION_LOGOUT_ALL = "user.logout_all"
ACTION_REMEMBER_ROTATED = "user.remember_rotated"

# Password
ACTION_PASSWORD_CHANGED = "user.password_changed"
ACTION_PASSWORD_RESET = "user.password_reset"

# Gestione utenti
ACTION_USER_CREATED = "user.created"
ACTION_USER_UPDATED = "user.updated"
ACTION_USER_DEACTIVATED = "user.deactivated"
ACTION_USER_REACTIVATED = "user.reactivated"

# Il registro che parla di se' stesso: l'esportazione in CSV e
# l'archiviazione su file compresso sono due operazioni come le altre, e come
# le altre lasciano una traccia. Un'esportazione e' una copia del registro che
# esce da Aurora: chi l'ha fatta e quando e' esattamente il genere di domanda
# a cui un audit deve saper rispondere.
ACTION_AUDIT_EXPORTED = "audit.exported"
ACTION_AUDIT_ARCHIVED = "audit.archived"

# La configurazione. Aurora non ha una pagina che la modifica - la
# configurazione sta nel file .env e nei file di config/, e si cambia sul
# server con un editore di testo (regola 8 di CLAUDE.md) - quindi non c'e'
# nessuna operazione dell'utente da registrare. Quello che si registra e' il
# **fatto** che la configurazione con cui il programma sta girando sia
# cambiata rispetto all'avvio precedente: lo rileva
# app/services/configuration.py alla partenza, confrontando i valori con
# l'ultima voce di questo tipo.
ACTION_CONFIG_LOADED = "config.loaded"
ACTION_CONFIG_CHANGED = "config.changed"

# Nome della tabella a cui si riferiscono le azioni sugli utenti.
ENTITY_USERS = "users"

# Il "tipo di entita'" delle voci che non parlano di una riga di una tabella
# ma del programma nel suo insieme: la configurazione, l'esportazione del
# registro. Non e' il nome di una tabella apposta: cosi' chi legge il registro
# vede subito che li' non c'e' nessun oggetto da aprire.
ENTITY_SISTEMA = "sistema"


# ---------------------------------------------------------------------------
#  2. IL CATALOGO
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TipoAzione:
    """Una delle operazioni che Aurora registra.

    codice     il nome dell'azione, in inglese, come finisce in
               audit_logs.action;
    etichetta  la frase italiana con cui comincia la descrizione della voce.
               E' al participio passato ("Documento caricato") perche' una
               riga di registro racconta un fatto avvenuto, non un comando;
    gruppo     a che cosa appartiene. Serve al menu dei filtri della pagina di
               consultazione: con sessanta azioni una tendina piatta non si
               legge.
    """

    codice: str
    etichetta: str
    gruppo: str


GRUPPO_ACCESSI = "Accessi"
GRUPPO_UTENTI = "Utenti"
GRUPPO_CLIENTI = "Clienti"
GRUPPO_PRODOTTI = "Prodotti e versioni"
GRUPPO_PROGETTI = "Progetti"
GRUPPO_DOCUMENTI = "Documenti"
GRUPPO_PERMESSI = "Permessi"
GRUPPO_FASI = "Fasi"
GRUPPO_POSTA = "Posta"
GRUPPO_SISTEMA = "Sistema"


def _tipi(*righe: tuple[str, str, str]) -> dict[str, TipoAzione]:
    """Costruisce il catalogo da un elenco di triple, tenendone l'ordine."""
    return {
        codice: TipoAzione(codice=codice, etichetta=etichetta, gruppo=gruppo)
        for codice, etichetta, gruppo in righe
    }


# **L'elenco delle operazioni che Aurora registra.** E' la risposta scritta
# alla domanda che fa chi verifica il programma: "quali operazioni lasciano
# traccia?". L'ordine e' quello in cui compaiono nel menu dei filtri.
CATALOGO: dict[str, TipoAzione] = _tipi(
    # --- Accessi ---------------------------------------------------------
    (ACTION_LOGIN, "Accesso riuscito", GRUPPO_ACCESSI),
    (ACTION_LOGIN_FAILED, "Accesso fallito", GRUPPO_ACCESSI),
    (ACTION_LOGIN_BLOCKED, "Accesso bloccato per troppi tentativi", GRUPPO_ACCESSI),
    (ACTION_LOGOUT, "Disconnessione", GRUPPO_ACCESSI),
    (ACTION_LOGOUT_ALL, "Disconnessione da tutti i dispositivi", GRUPPO_ACCESSI),
    (ACTION_REMEMBER_ROTATED, "Sessione «ricordami» rinnovata", GRUPPO_ACCESSI),
    # --- Utenti ----------------------------------------------------------
    (ACTION_USER_CREATED, "Utente creato", GRUPPO_UTENTI),
    (ACTION_USER_UPDATED, "Utente modificato", GRUPPO_UTENTI),
    (ACTION_USER_DEACTIVATED, "Utente disattivato", GRUPPO_UTENTI),
    (ACTION_USER_REACTIVATED, "Utente riattivato", GRUPPO_UTENTI),
    (ACTION_PASSWORD_CHANGED, "Password cambiata dall'interessato", GRUPPO_UTENTI),
    (
        ACTION_PASSWORD_RESET,
        "Password reimpostata da un amministratore",
        GRUPPO_UTENTI,
    ),
    # --- Clienti ---------------------------------------------------------
    ("customer.created", "Cliente creato", GRUPPO_CLIENTI),
    ("customer.updated", "Cliente modificato", GRUPPO_CLIENTI),
    ("customer.deactivated", "Cliente disattivato", GRUPPO_CLIENTI),
    ("customer.reactivated", "Cliente riattivato", GRUPPO_CLIENTI),
    ("contact.created", "Contatto creato", GRUPPO_CLIENTI),
    ("contact.updated", "Contatto modificato", GRUPPO_CLIENTI),
    ("contact.deactivated", "Contatto disattivato", GRUPPO_CLIENTI),
    # --- Prodotti e versioni ---------------------------------------------
    ("product.created", "Prodotto creato", GRUPPO_PRODOTTI),
    ("product.updated", "Prodotto modificato", GRUPPO_PRODOTTI),
    ("product.deactivated", "Prodotto disattivato", GRUPPO_PRODOTTI),
    ("product.reactivated", "Prodotto riattivato", GRUPPO_PRODOTTI),
    ("product_version.created", "Versione creata", GRUPPO_PRODOTTI),
    ("product_version.updated", "Versione modificata", GRUPPO_PRODOTTI),
    ("product_version.state_changed", "Ciclo di vita cambiato", GRUPPO_PRODOTTI),
    (
        "product_version.superseded",
        "Versione superata automaticamente",
        GRUPPO_PRODOTTI,
    ),
    # --- Progetti --------------------------------------------------------
    ("project.created", "Progetto aperto", GRUPPO_PROGETTI),
    ("assignment.created", "Persona assegnata al progetto", GRUPPO_PROGETTI),
    ("assignment.revoked", "Persona tolta dal progetto", GRUPPO_PROGETTI),
    # --- Documenti -------------------------------------------------------
    ("document.created", "Documento caricato", GRUPPO_DOCUMENTI),
    ("document.version_uploaded", "Versione del documento caricata", GRUPPO_DOCUMENTI),
    ("document.state_changed", "Stato del documento cambiato", GRUPPO_DOCUMENTI),
    ("document.deleted", "Documento ritirato", GRUPPO_DOCUMENTI),
    ("document.restored", "Documento ripristinato", GRUPPO_DOCUMENTI),
    ("document.download", "Documento scaricato", GRUPPO_DOCUMENTI),
    # --- Permessi --------------------------------------------------------
    ("permission_rule.changed", "Matrice dei permessi modificata", GRUPPO_PERMESSI),
    ("classification.created", "Classificazione creata", GRUPPO_PERMESSI),
    ("classification.renamed", "Classificazione rinominata", GRUPPO_PERMESSI),
    ("classification.moved", "Classificazione spostata", GRUPPO_PERMESSI),
    ("classification.deactivated", "Classificazione disattivata", GRUPPO_PERMESSI),
    ("classification.reactivated", "Classificazione riattivata", GRUPPO_PERMESSI),
    # --- Fasi ------------------------------------------------------------
    ("project.phase_entered", "Fase avanzata", GRUPPO_FASI),
    ("project.phase_requested", "Avanzamento di fase richiesto", GRUPPO_FASI),
    ("project.phase_approved", "Avanzamento di fase approvato", GRUPPO_FASI),
    ("project.phase_rejected", "Avanzamento di fase respinto", GRUPPO_FASI),
    ("project.phase_returned", "Ritorno a una fase precedente", GRUPPO_FASI),
    ("project.closed", "Progetto chiuso", GRUPPO_FASI),
    ("phase_template.created", "Modello di fasi creato", GRUPPO_FASI),
    ("phase_template.versioned", "Modello di fasi versionato", GRUPPO_FASI),
    ("phase_template.deactivated", "Modello di fasi disattivato", GRUPPO_FASI),
    ("phase_template.reactivated", "Modello di fasi riattivato", GRUPPO_FASI),
    # --- Posta -----------------------------------------------------------
    #
    # Le due righe "assigned_manual" e "quarantined" erano gia' qui dalla
    # sessione 9, scritte in anticipo per il giorno in cui la sezione della
    # posta sarebbe nata. La sessione 10 le mette in uso e ne aggiunge due:
    # l'archiviazione di un messaggio - che e' il fatto piu' frequente di
    # tutti, uno per messaggio letto - e lo scarico, che sulla corrispondenza
    # con i clienti si registra per la stessa ragione per cui si registra sui
    # documenti.
    #
    # Un messaggio archiviato produce **una riga sola**: "archived" se e' stato
    # attribuito, "quarantined" se no. Scriverne due per lo stesso fatto
    # renderebbe illeggibili i conteggi, e la differenza fra i due casi e'
    # proprio quello che la riga deve dire.
    ("email.archived", "Messaggio archiviato", GRUPPO_POSTA),
    ("email.quarantined", "Messaggio messo in quarantena", GRUPPO_POSTA),
    ("email.assigned_manual", "Messaggio assegnato a mano", GRUPPO_POSTA),
    ("email.download", "Messaggio o allegato scaricato", GRUPPO_POSTA),
    ("email_reason.created", "Motivo della posta creato", GRUPPO_POSTA),
    ("email_reason.updated", "Motivo della posta modificato", GRUPPO_POSTA),
    ("email_reason.deactivated", "Motivo della posta disattivato", GRUPPO_POSTA),
    ("email_reason.reactivated", "Motivo della posta riattivato", GRUPPO_POSTA),
    # --- Sistema ---------------------------------------------------------
    (ACTION_CONFIG_LOADED, "Configurazione letta all'avvio", GRUPPO_SISTEMA),
    (ACTION_CONFIG_CHANGED, "Configurazione cambiata", GRUPPO_SISTEMA),
    (ACTION_AUDIT_EXPORTED, "Registro esportato in CSV", GRUPPO_SISTEMA),
    (ACTION_AUDIT_ARCHIVED, "Registro archiviato su file compresso", GRUPPO_SISTEMA),
)


def tipo_azione(action: str) -> TipoAzione | None:
    """La riga del catalogo per un'azione, oppure None se non c'e'."""
    return CATALOGO.get(action)


def etichetta_azione(action: str) -> str:
    """La frase italiana di un'azione; l'azione stessa se non e' catalogata."""
    tipo = CATALOGO.get(action)
    return tipo.etichetta if tipo is not None else action


def opzioni_azioni() -> list[tuple[str, str]]:
    """Le azioni come coppie (codice, "Gruppo - Etichetta"), per una tendina.

    Le coppie si compongono qui e non nel template: comporre un elenco di
    scelte e' lavoro del codice (docs/GUIDA_STILE.md, sezione 5).
    """
    return [
        (tipo.codice, f"{tipo.gruppo} - {tipo.etichetta}")
        for tipo in CATALOGO.values()
    ]


def opzioni_gruppi() -> list[tuple[str, str]]:
    """I gruppi di azioni come coppie (nome, nome), senza ripetizioni."""
    visti: list[str] = []
    for tipo in CATALOGO.values():
        if tipo.gruppo not in visti:
            visti.append(tipo.gruppo)
    return [(gruppo, gruppo) for gruppo in visti]


def azioni_del_gruppo(gruppo: str) -> list[str]:
    """I codici delle azioni che appartengono a un gruppo."""
    return [tipo.codice for tipo in CATALOGO.values() if tipo.gruppo == gruppo]


# ---------------------------------------------------------------------------
#  3. LA DESCRIZIONE IN ITALIANO
# ---------------------------------------------------------------------------

# Quanti campi cambiati si scrivono per esteso nella descrizione prima di
# fermarsi. Tre bastano a capire che cosa e' successo; il dettaglio completo
# resta comunque in old_value e new_value, che la pagina di consultazione
# mostra per intero.
MASSIMO_CAMPI_NELLA_DESCRIZIONE = 3


def _leggibile(valore: Any) -> str:
    """Un valore come lo si vuole leggere dentro una frase italiana."""
    if valore is None:
        return "(vuoto)"
    if isinstance(valore, bool):
        return "si" if valore else "no"
    if isinstance(valore, (list, tuple)):
        return ", ".join(_leggibile(elemento) for elemento in valore) or "(vuoto)"
    testo = str(valore)
    return testo if testo != "" else "(vuoto)"


def _cambiamenti(
    old_value: dict[str, Any] | None, new_value: dict[str, Any] | None
) -> str:
    """La frase "campo: prima -> dopo" per i campi che sono cambiati.

    Quando il valore precedente non c'e' - una creazione - si scrive il solo
    valore nuovo: "codice: (vuoto) -> RMS1100" direbbe una cosa vera e
    inutile.
    """
    if not new_value:
        return ""

    pezzi: list[str] = []
    for campo, dopo in new_value.items():
        if old_value is not None and campo in old_value:
            prima = old_value[campo]
            if prima == dopo:
                continue
            pezzi.append(f"{campo}: {_leggibile(prima)} -> {_leggibile(dopo)}")
        else:
            pezzi.append(f"{campo}: {_leggibile(dopo)}")

    if not pezzi:
        return ""

    if len(pezzi) > MASSIMO_CAMPI_NELLA_DESCRIZIONE:
        restanti = len(pezzi) - MASSIMO_CAMPI_NELLA_DESCRIZIONE
        pezzi = pezzi[:MASSIMO_CAMPI_NELLA_DESCRIZIONE]
        pezzi.append(f"e altri {restanti} campi")

    return "; ".join(pezzi)


def descrizione_predefinita(
    action: str,
    etichetta: str | None = None,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
) -> str:
    """Compone la frase italiana che descrive una voce del registro.

    Tre pezzi, e gli ultimi due sono facoltativi:

        Documento caricato: Schema elettrico (stato: bozza -> in_verifica)
        [___ dal catalogo _]  [_ l'oggetto _] [___ da old_value/new_value ___]

    "etichetta" e' il nome con cui una persona chiama l'oggetto: il titolo di
    un documento, il codice di un prodotto, il nome utente. Lo passa chi
    chiama record(), perche' e' l'unico che ce l'ha sotto mano; qui non si
    interroga il database, perche' una funzione che scrive nel registro non
    deve andare a cercarsi i dati - se lo facesse, il registro rallenterebbe
    ogni operazione del programma.
    """
    tipo = CATALOGO.get(action)
    if tipo is None:
        # Non si interrompe niente: una voce con la descrizione approssimata
        # e' infinitamente meglio di un'operazione non registrata. Ma l'errore
        # va nel registro su file, perche' vuol dire che qualcuno ha aggiunto
        # un'azione senza catalogarla, e il filtro della pagina di
        # consultazione non la propone.
        logger.error(
            "l'azione '%s' non e' in audit.CATALOGO: la voce viene scritta "
            "lo stesso, ma con una descrizione approssimata e senza comparire "
            "fra i tipi di azione della pagina /registro",
            action,
        )
        testo = f"Operazione «{action}»"
    else:
        testo = tipo.etichetta

    if etichetta:
        testo = f"{testo}: {etichetta}"

    dettaglio = _cambiamenti(old_value, new_value)
    if dettaglio:
        testo = f"{testo} ({dettaglio})"

    return testo


# ---------------------------------------------------------------------------
#  4. LA CATENA DELLE IMPRONTE
# ---------------------------------------------------------------------------

# L'impronta che sta prima della prima voce. Sessantaquattro zeri: non e'
# l'impronta di niente - SHA-256 non produce mai tutti zeri - quindi non si
# puo' confondere con quella di una voce vera.
IMPRONTA_ZERO = "0" * 64

# Il numero del lucchetto consultivo di PostgreSQL con cui si serializza
# l'assegnazione dei numeri di sequenza. E' un numero qualunque, purche' sia
# sempre lo stesso: due transazioni che chiedono lo stesso numero aspettano
# l'una l'altra.
LUCCHETTO_CATENA = 903_090_009

# Dove si tengono, dentro la sessione, le voci in attesa di essere incatenate.
# Sta in Session.info e non in una variabile di modulo perche' le sessioni
# sono tante - una per richiesta HTTP - e ciascuna ha le sue.
CHIAVE_IN_ATTESA = "aurora_audit_in_attesa"


def _testo_json(valore: dict[str, Any] | None) -> str:
    """Un JSON scritto sempre allo stesso modo, per poterlo dare in pasto a SHA.

    Le chiavi ordinate e nessuno spazio: PostgreSQL, rileggendo una colonna
    jsonb, puo' restituire le chiavi in un ordine diverso da quello in cui
    sono state scritte, e senza questa normalizzazione l'impronta ricalcolata
    da scripts/verifica_audit.py non tornerebbe mai.
    """
    if valore is None:
        return ""
    return json.dumps(
        valore, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )


def _testo_ora(momento: datetime | None) -> str:
    """L'istante riportato a UTC e scritto in forma ISO.

    Sempre a UTC: la stessa riga riletta da un collegamento con un fuso
    diverso darebbe altrimenti un testo diverso e un'impronta diversa.
    """
    if momento is None:
        return ""
    if momento.tzinfo is None:
        # Non dovrebbe capitare: la colonna e' timestamptz e record() scrive
        # sempre un'ora con fuso. Se capita, la si considera UTC e si va
        # avanti, perche' una verifica che si interrompe non verifica niente.
        momento = momento.replace(tzinfo=timezone.utc)
    return momento.astimezone(timezone.utc).isoformat()


def impronta(
    *,
    seq: int,
    occurred_at: datetime | None,
    user_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    old_value: dict[str, Any] | None,
    new_value: dict[str, Any] | None,
    ip: str | None,
    description: str,
    previous_hash: str,
) -> str:
    """L'impronta SHA-256 di una voce del registro.

    **Prende i campi uno per uno e non l'oggetto AuditLog** perche' la stessa
    funzione la usa scripts/verifica_audit.py, che legge le righe con SQL
    diretto e non ha nessun oggetto in mano. Se le due strade calcolassero
    l'impronta in due modi diversi, la verifica direbbe che il registro e'
    manomesso tutte le volte.

    Dentro l'impronta ci sono **tutte** le colonne che raccontano il fatto,
    piu' il numero di sequenza e l'impronta della voce precedente. Fuori
    restano solo id, created_at e updated_at, che del fatto non dicono niente
    e che il database riempie da solo.

    Ogni pezzo viene preceduto dalla sua lunghezza ("28:Documento caricato").
    Serve perche' la descrizione e' testo libero e potrebbe contenere il
    separatore: senza le lunghezze, due voci diverse potrebbero produrre la
    stessa stringa spostando una barra dentro un testo, e quindi la stessa
    impronta.
    """
    pezzi = [
        str(seq),
        _testo_ora(occurred_at),
        str(user_id) if user_id else "",
        action,
        entity_type,
        str(entity_id) if entity_id else "",
        _testo_json(old_value),
        _testo_json(new_value),
        ip or "",
        description,
        previous_hash,
    ]
    materiale = "|".join(f"{len(pezzo)}:{pezzo}" for pezzo in pezzi)
    return hashlib.sha256(materiale.encode("utf-8")).hexdigest()


def impronta_della_riga(riga: AuditLog) -> str:
    """L'impronta di una voce che si ha gia' in mano come oggetto."""
    return impronta(
        seq=riga.seq,
        occurred_at=riga.occurred_at,
        user_id=riga.user_id,
        action=riga.action,
        entity_type=riga.entity_type,
        entity_id=riga.entity_id,
        old_value=riga.old_value,
        new_value=riga.new_value,
        ip=riga.ip,
        description=riga.description,
        previous_hash=riga.previous_hash,
    )


@event.listens_for(Session, "before_flush")
def _incatena_le_voci_nuove(
    session: Session, contesto: object, istanze: object
) -> None:
    """Assegna numero di sequenza e impronte alle voci in partenza.

    **Perche' qui e non dentro record().** Fra la chiamata a record() e il
    momento in cui la riga arriva davvero al database possono passare altre
    operazioni, e la catena deve rispecchiare l'ordine in cui le righe
    vengono scritte, non quello in cui sono state preparate. Il flush e' il
    momento esatto in cui quell'ordine si decide, ed e' l'unico posto in cui
    si puo' guardare il database sapendo che nessun altro sta scrivendo.

    **Perche' il lucchetto.** Due richieste che registrano un'operazione nello
    stesso istante leggerebbero tutte e due l'ultima impronta e ne
    scriverebbero due con lo stesso "precedente": la catena si biforcherebbe.
    pg_advisory_xact_lock fa aspettare la seconda finche' la prima non ha
    chiuso la sua transazione. Costa una serializzazione delle sole scritture
    del registro; per qualche decina di utenti in rete locale non si vede, e
    il vincolo di unicita' su "seq" e' li' a dire che non stiamo indovinando.

    Il lucchetto si rilascia da solo alla fine della transazione, riuscita o
    fallita che sia: e' quello che vuol dire "xact" nel nome.

    **Una riga di audit_logs aggiunta senza passare da record() non arriva
    qui**, quindi resta senza numero di sequenza e l'INSERT fallisce sul
    vincolo NOT NULL. E' voluto: e' il modo in cui il database fa rispettare
    D-018, cioe' che l'unica porta d'ingresso del registro sia record().
    """
    in_attesa: list[AuditLog] = session.info.get(CHIAVE_IN_ATTESA) or []
    if not in_attesa:
        return

    # Solo quelle che stanno davvero per essere scritte: una transazione
    # annullata lascia in coda oggetti che al database non arriveranno mai, e
    # farli entrare nella catena vorrebbe dire lasciarci dentro dei buchi.
    nuove = [riga for riga in in_attesa if riga in session.new]
    session.info[CHIAVE_IN_ATTESA] = []
    if not nuove:
        return

    connessione = session.connection()
    connessione.execute(
        text("SELECT pg_advisory_xact_lock(:chiave)"), {"chiave": LUCCHETTO_CATENA}
    )

    ultima = connessione.execute(
        text("SELECT seq, entry_hash FROM audit_logs ORDER BY seq DESC LIMIT 1")
    ).first()

    numero = ultima.seq if ultima is not None else 0
    precedente = ultima.entry_hash if ultima is not None else IMPRONTA_ZERO

    for riga in nuove:
        numero += 1
        riga.seq = numero
        riga.previous_hash = precedente
        riga.entry_hash = impronta_della_riga(riga)
        precedente = riga.entry_hash


# ---------------------------------------------------------------------------
#  5. LA SCRITTURA
# ---------------------------------------------------------------------------


def client_ip(request: Request | None) -> str | None:
    """Estrae l'indirizzo IP di chi ha fatto la richiesta.

    Restituisce None quando l'indirizzo non e' disponibile: succede nei test,
    dove non c'e' nessuna connessione di rete vera.

    Attenzione per la sessione 13: se un giorno Aurora verra' messa dietro a
    un proxy inverso (IIS, nginx), qui arrivera' l'indirizzo del proxy e non
    quello dell'utente. In quel caso andra' letta l'intestazione
    X-Forwarded-For, ma **solo** fidandosi del proxy, altrimenti chiunque
    potrebbe scrivere nel registro l'indirizzo che preferisce.
    """
    if request is None or request.client is None:
        return None
    return request.client.host


def record(
    db: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    request: Request | None = None,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    etichetta: str | None = None,
    description: str | None = None,
) -> AuditLog:
    """Aggiunge una riga al registro delle operazioni.

    La riga viene solo aggiunta alla sessione del database: **non** viene
    scritta subito. Il commit lo fa chi sta gestendo la richiesta, insieme
    all'operazione che la riga descrive. Cosi' o si scrivono tutte e due o non
    se ne scrive nessuna, e non capita mai di leggere nel registro un fatto
    che poi non e' avvenuto.

    Gli argomenti dopo "db" si passano per nome (e' quello che impone
    l'asterisco): sono dieci, quasi tutti dello stesso tipo, e passarli per
    posizione sarebbe un invito a scambiarne due.

    In old_value e new_value vanno **solo i campi cambiati**, mai la riga
    intera, e mai niente che riguardi le password: nemmeno l'impronta.

    Gli ultimi due argomenti sono quelli della sessione 9 e servono alla
    descrizione in italiano:

      etichetta    il nome con cui una persona chiama l'oggetto - il titolo
                   del documento, il codice del prodotto, il nome utente. E'
                   quello che si passa quasi sempre;
      description  la frase gia' pronta, per i pochi casi in cui la
                   composizione automatica direbbe una cosa goffa. Quando c'e'
                   vince lei, ed "etichetta" non viene guardata.

    Numero di sequenza e impronte non si passano: li assegna il flush, poco
    piu' sopra in questo file.
    """
    momento = datetime.now(timezone.utc)

    if description is None:
        description = descrizione_predefinita(action, etichetta, old_value, new_value)

    riga = AuditLog(
        # L'ora la mette Python e non il database. Due ragioni: e' l'istante
        # in cui il fatto e' avvenuto e non quello in cui la riga viene
        # scritta (sono due cose diverse, ed e' il motivo per cui esistono sia
        # occurred_at sia created_at), e serve gia' valorizzata per calcolare
        # l'impronta prima dell'INSERT.
        occurred_at=momento,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=user_id,
        ip=client_ip(request),
        old_value=old_value,
        new_value=new_value,
        description=description,
    )
    db.add(riga)

    # In coda alle voci che il prossimo flush dovra' incatenare, nell'ordine
    # in cui sono state chieste.
    in_attesa: list[AuditLog] = db.info.setdefault(CHIAVE_IN_ATTESA, [])
    in_attesa.append(riga)

    # Una copia nel registro su file: quando si indaga su un problema si
    # guarda logs/aurora.log, e avere le due tracce affiancate nel tempo fa
    # risparmiare mezz'ora.
    logger.info(
        "audit %s su %s/%s da utente=%s ip=%s | %s",
        action,
        entity_type,
        entity_id,
        user_id,
        riga.ip,
        description,
    )

    return riga
