"""Lettura del registro delle operazioni: ricerca, storico, esportazione, verifica.

Il registro lo **scrive** app/services/audit.py, ed e' l'unico che lo scrive
(D-018). Questo file non scrive niente: lo interroga. Sono due mestieri
diversi e stanno in due file diversi perche' quello che scrive deve restare
corto e leggibile in una schermata - e' il file su cui si va a controllare che
un'operazione lasci traccia - mentre le interrogazioni sono tante e crescono.

Qui dentro ci sono quattro cose:

  cerca()            l'elenco filtrato che disegna la pagina /registro;
  voci_collegate()   lo storico di un singolo oggetto, per la sua scheda;
  righe_csv()        le stesse voci scritte per l'esportazione;
  verifica_catena()  il ricalcolo delle impronte, che dice se qualcuno ha
                     messo le mani nel database scavalcando il programma.

L'ultima e' quella che usa scripts/verifica_audit.py. Sta qui e non nello
script per la stessa ragione per cui la logica sta sempre in un servizio:
cosi' la esercita anche un test, e uno script che nessun test esercita e' uno
script che smette di funzionare senza che nessuno se ne accorga.
"""

import logging
import uuid
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.models import AuditLog, User
from app.services import audit

logger = logging.getLogger("aurora.registro")


# ---------------------------------------------------------------------------
#  1. I TIPI DI ENTITA'
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TipoEntita:
    """Un tipo di oggetto su cui il registro puo' avere qualcosa da dire.

    codice     il valore che finisce in audit_logs.entity_type, cioe' il nome
               della tabella;
    etichetta  come si chiama in italiano, al singolare;
    indirizzo  il modello dell'indirizzo della scheda dell'oggetto, con {id}
               al posto dell'identificatore. Vale None per le entita' che una
               scheda non ce l'hanno: un'assegnazione, una casella della
               matrice, il programma nel suo insieme. In quel caso la pagina
               del registro mostra il tipo e non ci mette il collegamento.
    """

    codice: str
    etichetta: str
    indirizzo: str | None = None


# I tipi di entita' che compaiono nel registro. E' un elenco scritto e non
# una SELECT DISTINCT sulla tabella: un elenco di filtri che cambia a seconda
# di quello che e' successo di recente e' un elenco su cui non ci si puo'
# appoggiare, e la DISTINCT su un registro di anni costa.
ENTITA: dict[str, TipoEntita] = {
    tipo.codice: tipo
    for tipo in (
        TipoEntita("users", "Utente", "/utenti/{id}"),
        TipoEntita("customers", "Cliente", "/clienti/{id}"),
        TipoEntita("contacts", "Contatto"),
        TipoEntita("products", "Prodotto", "/prodotti/{id}"),
        TipoEntita("product_versions", "Versione", "/versioni/{id}"),
        TipoEntita("projects", "Progetto", "/progetti/{id}"),
        TipoEntita("assignments", "Assegnazione"),
        TipoEntita("documents", "Documento", "/documenti/{id}"),
        TipoEntita("classifications", "Classificazione"),
        TipoEntita("permission_rules", "Matrice dei permessi"),
        TipoEntita("phase_templates", "Modello di fasi", "/fasi/{id}"),
        TipoEntita("phase_transitions", "Passaggio di fase"),
        TipoEntita("email_messages", "Messaggio di posta"),
        TipoEntita(audit.ENTITY_SISTEMA, "Sistema"),
    )
}


def etichetta_entita(entity_type: str) -> str:
    """Il nome italiano di un tipo di entita'; il codice se non e' catalogato."""
    tipo = ENTITA.get(entity_type)
    return tipo.etichetta if tipo is not None else entity_type


def indirizzo_entita(entity_type: str, entity_id: uuid.UUID | None) -> str | None:
    """L'indirizzo della scheda dell'oggetto, se ne ha una.

    Restituisce None quando l'oggetto una pagina non ce l'ha, e anche quando
    l'identificatore manca: un collegamento a "/documenti/None" e' peggio di
    nessun collegamento.
    """
    tipo = ENTITA.get(entity_type)
    if tipo is None or tipo.indirizzo is None or entity_id is None:
        return None
    return tipo.indirizzo.format(id=entity_id)


def opzioni_entita() -> list[tuple[str, str]]:
    """I tipi di entita' come coppie (codice, etichetta), per la tendina."""
    return [(tipo.codice, tipo.etichetta) for tipo in ENTITA.values()]


# ---------------------------------------------------------------------------
#  2. LA RICERCA
# ---------------------------------------------------------------------------

# Il valore del filtro "utente" che vuol dire "le operazioni senza persona",
# cioe' quelle che ha fatto il programma da solo. Non e' un identificatore
# perche' non c'e' nessuna riga da identificare: la colonna user_id e' nulla.
UTENTE_SISTEMA = "sistema"


@dataclass(frozen=True)
class Filtro:
    """Le condizioni scelte nella barra di ricerca della pagina /registro.

    Tutti i campi sono facoltativi: un filtro vuoto vuol dire "tutto il
    registro". Sono un oggetto solo e non sette argomenti perche' passano di
    mano tre volte - dalla rotta alla ricerca, dalla rotta all'esportazione,
    dalla rotta all'impaginazione - e sette argomenti che viaggiano insieme
    prima o poi si mescolano.
    """

    dal_giorno: date | None = None
    al_giorno: date | None = None
    utente: str = ""
    azione: str = ""
    gruppo: str = ""
    entita: str = ""
    testo: str = ""

    def e_vuoto(self) -> bool:
        """Vero quando non e' stato scelto nessun filtro."""
        return not any(
            (
                self.dal_giorno,
                self.al_giorno,
                self.utente,
                self.azione,
                self.gruppo,
                self.entita,
                self.testo.strip(),
            )
        )

    def parametri(self) -> dict[str, str]:
        """I filtri scelti, come parametri da rimettere nell'indirizzo.

        Servono all'impaginazione e al pulsante di esportazione: senza,
        cambiare pagina o esportare azzererebbe la ricerca appena fatta. Le
        voci non valorizzate si omettono, non si passano vuote.
        """
        tutti = {
            "dal": self.dal_giorno.isoformat() if self.dal_giorno else "",
            "al": self.al_giorno.isoformat() if self.al_giorno else "",
            "utente": self.utente,
            "azione": self.azione,
            "gruppo": self.gruppo,
            "entita": self.entita,
            "q": self.testo.strip(),
        }
        return {nome: valore for nome, valore in tutti.items() if valore}


def _condizioni(filtro: Filtro) -> list:
    """Traduce il filtro in condizioni SQL, una per campo valorizzato."""
    condizioni = []

    # Le due date sono giorni interi, come li intende chi li scrive: "dal 3
    # agosto" vuol dire dalle 00:00 del 3, "al 3 agosto" vuol dire fino alle
    # 23:59:59 del 3, non fino alla mezzanotte che lo apre. Un intervallo che
    # esclude il giorno finale e' l'errore che fa perdere mezz'ora a chi cerca
    # un'operazione fatta oggi.
    #
    # astimezone() senza argomenti attacca il fuso del server, che e' quello
    # in cui l'ora viene poi mostrata: cosi' il filtro seleziona lo stesso
    # giorno che si legge nella colonna.
    if filtro.dal_giorno is not None:
        inizio = datetime.combine(filtro.dal_giorno, time.min).astimezone()
        condizioni.append(AuditLog.occurred_at >= inizio)

    if filtro.al_giorno is not None:
        fine = datetime.combine(filtro.al_giorno, time.max).astimezone()
        condizioni.append(AuditLog.occurred_at <= fine)

    if filtro.utente == UTENTE_SISTEMA:
        condizioni.append(AuditLog.user_id.is_(None))
    elif filtro.utente:
        try:
            condizioni.append(AuditLog.user_id == uuid.UUID(filtro.utente))
        except ValueError:
            # Un identificatore scritto male nell'indirizzo non e' un guasto:
            # si ignora il filtro, come fa l'elenco dei prodotti.
            logger.info("filtro utente non valido nel registro: %r", filtro.utente)

    if filtro.azione:
        condizioni.append(AuditLog.action == filtro.azione)
    elif filtro.gruppo:
        # Il gruppo si applica solo quando non e' stata scelta un'azione
        # precisa: sceglierle tutte e due vorrebbe dire "le azioni di questo
        # gruppo, ma solo quella", che e' l'azione da sola.
        azioni = audit.azioni_del_gruppo(filtro.gruppo)
        if azioni:
            condizioni.append(AuditLog.action.in_(azioni))

    if filtro.entita:
        condizioni.append(AuditLog.entity_type == filtro.entita)

    testo = filtro.testo.strip()
    if testo:
        # La ricerca testuale e' sulla descrizione, che e' la colonna scritta
        # perche' una persona la legga. Cercare dentro old_value e new_value
        # vorrebbe dire cercare dentro del JSON, e chi cerca "Schema
        # elettrico" non sta pensando al JSON.
        #
        # ilike e' insensibile alle maiuscole. I caratteri jolly di SQL si
        # neutralizzano: chi cerca "50%" cerca "50%", non "50 seguito da
        # qualunque cosa".
        modello = testo.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        condizioni.append(AuditLog.description.ilike(f"%{modello}%", escape="\\"))

    return condizioni


def _interrogazione(condizioni: Sequence) -> Select:
    """L'interrogazione di base: le voci che soddisfano le condizioni.

    L'ordine e' sempre per numero di sequenza decrescente, cioe' dalla piu'
    recente alla piu' vecchia. Si ordina per "seq" e non per "occurred_at"
    perche' seq e' un ordine **totale**: due voci scritte nello stesso
    centesimo di secondo hanno la stessa ora, e un'impaginazione appoggiata a
    un ordine ambiguo puo' mostrare due volte la stessa riga saltandone
    un'altra.
    """
    return (
        select(AuditLog)
        .where(*condizioni)
        .options(joinedload(AuditLog.user))
        .order_by(AuditLog.seq.desc())
    )


def cerca(
    db: Session,
    filtro: Filtro,
    *,
    pagina: int = 1,
    per_pagina: int = 25,
) -> tuple[list[AuditLog], int]:
    """Le voci che soddisfano il filtro, una pagina per volta.

    Restituisce la pagina chiesta e **quante voci ci sono in tutto**, che e'
    il numero che serve all'impaginazione.
    """
    condizioni = _condizioni(filtro)

    totale = db.scalar(select(func.count()).select_from(AuditLog).where(*condizioni))
    totale = int(totale or 0)

    salto = max(0, (pagina - 1) * per_pagina)
    righe = list(
        db.scalars(_interrogazione(condizioni).offset(salto).limit(per_pagina)).all()
    )

    return righe, totale


def tutte(db: Session, filtro: Filtro, *, massimo: int) -> list[AuditLog]:
    """Tutte le voci che soddisfano il filtro, fino a un tetto.

    Serve all'esportazione. Il tetto c'e' apposta: un'esportazione senza
    filtri su un registro di cinque anni sarebbe un file da centinaia di
    megabyte preparato in memoria, e il server aziendale ha altro da fare.
    Chi ha bisogno di tutto usa scripts/archivia_audit.py, che scrive su
    disco a blocchi.
    """
    condizioni = _condizioni(filtro)
    return list(db.scalars(_interrogazione(condizioni).limit(massimo)).all())


def voci_collegate(
    db: Session,
    *,
    entity_ids: Sequence[uuid.UUID] = (),
    autore_id: uuid.UUID | None = None,
    pagina: int = 1,
    per_pagina: int = 25,
) -> tuple[list[AuditLog], int]:
    """Lo storico di un oggetto: le voci che parlano di lui.

    E' quello che disegna la scheda "Storico" di un prodotto, di una versione,
    di un progetto, di un documento, di una persona.

    **Si cerca per identificatore e non per coppia (tipo, identificatore)**
    perche' gli identificatori sono UUID generati a caso: due righe di due
    tabelle diverse non possono avere lo stesso. Cosi' chi chiama passa un
    elenco di identificatori e basta, e la storia di un progetto puo'
    comprendere le sue assegnazioni e i suoi passaggi di fase, che nel
    registro sono voci con un tipo di entita' diverso.

    "autore_id" aggiunge le voci **fatte da** una persona, che e' l'altra
    meta' della storia di un utente: la sua scheda deve mostrare sia quello
    che le hanno fatto sia quello che ha fatto lei.
    """
    condizioni = []

    if entity_ids:
        condizioni.append(AuditLog.entity_id.in_(list(entity_ids)))
    if autore_id is not None:
        condizioni.append(AuditLog.user_id == autore_id)

    if not condizioni:
        return [], 0

    # or_ e non and_: sono due modi diversi di essere "collegato a questo
    # oggetto", non due condizioni da soddisfare insieme.
    dove = [or_(*condizioni)] if len(condizioni) > 1 else condizioni

    conteggio = db.scalar(select(func.count()).select_from(AuditLog).where(*dove))
    totale = int(conteggio or 0)

    salto = max(0, (pagina - 1) * per_pagina)
    righe = list(
        db.scalars(_interrogazione(dove).offset(salto).limit(per_pagina)).all()
    )

    return righe, totale


# ---------------------------------------------------------------------------
#  3. GLI UTENTI DA PROPORRE NEL FILTRO
# ---------------------------------------------------------------------------


def opzioni_utenti(db: Session) -> list[tuple[str, str]]:
    """Le persone che compaiono nel registro, come coppie per la tendina.

    Sono **le persone che hanno fatto qualcosa**, non tutti gli utenti: un
    filtro che propone un nome per cui non c'e' niente da trovare fa credere
    a chi lo usa che il registro sia incompleto.

    La prima voce e' "il programma": le operazioni fatte da un lavoro
    pianificato o dall'avvio del server hanno user_id nullo, e devono essere
    cercabili come le altre.
    """
    presenti = (
        select(AuditLog.user_id)
        .where(AuditLog.user_id.is_not(None))
        .distinct()
        .scalar_subquery()
    )
    utenti = db.scalars(
        select(User).where(User.id.in_(presenti)).order_by(User.username)
    ).all()

    return [(UTENTE_SISTEMA, "Il programma (sistema)")] + [
        (str(utente.id), utente.username) for utente in utenti
    ]


def nome_autore(riga: AuditLog) -> str:
    """Chi ha fatto l'operazione, come si scrive in una tabella.

    Le voci senza persona sono quelle del programma: un lavoro pianificato,
    la lettura della configurazione all'avvio. Si scrive "sistema" e non si
    lascia vuoto, perche' una cella vuota sembra un dato mancante.
    """
    if riga.user is not None:
        return riga.user.username
    return "sistema"


# ---------------------------------------------------------------------------
#  4. L'ESPORTAZIONE IN CSV
# ---------------------------------------------------------------------------

# Le colonne del file esportato, nell'ordine in cui compaiono. Le
# intestazioni sono in italiano perche' il file lo apre una persona, non un
# programma.
COLONNE_CSV = (
    "N.",
    "Data e ora",
    "Utente",
    "Azione",
    "Codice azione",
    "Tipo entita'",
    "Identificativo entita'",
    "Descrizione",
    "Valore precedente",
    "Valore successivo",
    "Indirizzo IP",
    "Impronta",
    "Impronta precedente",
)


def _valore_csv(valore: dict | None) -> str:
    """Un old_value o new_value scritto per una cella di foglio elettronico.

    Non JSON: "stato=bozza; motivo=prima stesura" si legge dentro una cella,
    mentre le graffe e le virgolette del JSON fanno diventare la colonna
    illeggibile appena ci sono due campi.
    """
    if not valore:
        return ""
    return "; ".join(f"{campo}={valore[campo]}" for campo in sorted(valore))


def righe_csv(
    voci: Iterable[AuditLog], intestazione: bool = True
) -> Iterator[list[str]]:
    """Le voci come righe di CSV, intestazione compresa.

    Le impronte ci sono apposta: un'esportazione che le omettesse sarebbe una
    copia del registro che non si puo' piu' verificare, e chi la riceve
    dovrebbe fidarsi sulla parola.

    "intestazione" si mette a falso quando si scrive un file a blocchi e la
    prima riga e' gia' stata scritta: la usa scripts/archivia_audit.py, che su
    un registro di anni non puo' tenere tutte le voci in memoria insieme.
    """
    if intestazione:
        yield list(COLONNE_CSV)

    for voce in voci:
        yield [
            str(voce.seq),
            voce.occurred_at.astimezone().strftime("%d/%m/%Y %H:%M:%S %z"),
            nome_autore(voce),
            audit.etichetta_azione(voce.action),
            voce.action,
            etichetta_entita(voce.entity_type),
            str(voce.entity_id) if voce.entity_id else "",
            voce.description,
            _valore_csv(voce.old_value),
            _valore_csv(voce.new_value),
            voce.ip or "",
            voce.entry_hash,
            voce.previous_hash,
        ]


# ---------------------------------------------------------------------------
#  5. LA VERIFICA DELLA CATENA
# ---------------------------------------------------------------------------


@dataclass
class Anomalia:
    """Qualcosa che nella catena non torna.

    seq        il numero della voce a cui si riferisce
    genere     che tipo di problema e'
    spiegazione  la frase in italiano da mostrare a chi legge
    """

    seq: int
    genere: str
    spiegazione: str


# I tre generi di anomalia. Sono costanti e non stringhe scritte a mano
# perche' compaiono in due posti (qui e nello script) e una svista di
# battitura produrrebbe un genere nuovo che non conta nessuno.
ANOMALIA_IMPRONTA = "impronta"
ANOMALIA_COLLEGAMENTO = "collegamento"
ANOMALIA_BUCO = "buco"


@dataclass
class Esito:
    """Il risultato della verifica della catena."""

    voci_esaminate: int = 0
    anomalie: list[Anomalia] = field(default_factory=list)

    @property
    def integro(self) -> bool:
        """Vero quando non e' stata trovata nessuna anomalia."""
        return not self.anomalie


def verifica_catena(db: Session, *, dal_numero: int = 1) -> Esito:
    """Ricalcola le impronte di tutto il registro e segnala che cosa non torna.

    Tre controlli, e sono tre cose diverse:

      1. **l'impronta della voce** ricalcolata dai suoi campi deve essere
         quella scritta nella colonna. Se non lo e', qualcuno ha cambiato il
         contenuto di quella riga;

      2. **l'impronta precedente** scritta nella voce deve essere quella della
         voce che la precede davvero. Se non lo e', qualcuno ha tolto una
         riga o ne ha infilata una in mezzo;

      3. **i numeri di sequenza** devono essere consecutivi. Un buco vuol dire
         una riga cancellata - cosa che l'utente applicativo non puo' fare
         (scripts/hardening_db.sql), quindi vuol dire che e' stata fatta da
         chi amministra il database.

    Le voci si leggono a blocchi e non tutte insieme: un registro di cinque
    anni non entra in memoria, e uno strumento di verifica che va in
    difficolta' proprio sui registri grossi non serve a niente.

    "dal_numero" serve a riprendere una verifica da dove si era arrivati.
    Attenzione: partendo da un numero diverso da 1 il controllo 2 non puo'
    essere fatto sulla prima voce esaminata, perche' quella precedente non e'
    stata letta. Lo script lo dice a chi lo usa.
    """
    esito = Esito()

    precedente_attesa: str | None = None
    numero_atteso = dal_numero

    blocco = 500
    ultimo_visto = dal_numero - 1

    while True:
        righe = list(
            db.scalars(
                select(AuditLog)
                .where(AuditLog.seq > ultimo_visto)
                .order_by(AuditLog.seq)
                .limit(blocco)
            ).all()
        )
        if not righe:
            break

        for riga in righe:
            ultimo_visto = riga.seq
            esito.voci_esaminate += 1

            if riga.seq != numero_atteso:
                mancanti = riga.seq - numero_atteso
                esito.anomalie.append(
                    Anomalia(
                        seq=riga.seq,
                        genere=ANOMALIA_BUCO,
                        spiegazione=(
                            f"manca{'no' if mancanti > 1 else ''} "
                            f"{mancanti} voce{'i' if mancanti > 1 else ''} "
                            f"fra il numero {numero_atteso - 1} e il numero "
                            f"{riga.seq}: qualcuno ha tolto delle righe"
                        ),
                    )
                )

            ricalcolata = audit.impronta_della_riga(riga)
            if ricalcolata != riga.entry_hash:
                esito.anomalie.append(
                    Anomalia(
                        seq=riga.seq,
                        genere=ANOMALIA_IMPRONTA,
                        spiegazione=(
                            "il contenuto di questa voce non corrisponde alla "
                            "sua impronta: e' stato modificato dopo la "
                            f"scrittura (descrizione: {riga.description!r})"
                        ),
                    )
                )

            aggancio_sbagliato = (
                precedente_attesa is not None
                and riga.previous_hash != precedente_attesa
            )
            if aggancio_sbagliato:
                esito.anomalie.append(
                    Anomalia(
                        seq=riga.seq,
                        genere=ANOMALIA_COLLEGAMENTO,
                        spiegazione=(
                            "questa voce non si aggancia a quella prima: "
                            "l'impronta precedente che porta scritta non e' "
                            "quella della voce che la precede"
                        ),
                    )
                )
            elif precedente_attesa is None and riga.seq == 1:
                # La primissima voce del registro deve agganciarsi al niente.
                if riga.previous_hash != audit.IMPRONTA_ZERO:
                    esito.anomalie.append(
                        Anomalia(
                            seq=riga.seq,
                            genere=ANOMALIA_COLLEGAMENTO,
                            spiegazione=(
                                "la prima voce del registro dovrebbe agganciarsi "
                                "all'impronta di partenza (tutti zeri) e non lo fa: "
                                "sono state tolte delle voci dall'inizio"
                            ),
                        )
                    )

            # Si prosegue dall'impronta **scritta**, non da quella ricalcolata:
            # cosi' una riga manomessa produce una sola anomalia invece di
            # farne comparire una su tutte le righe successive.
            precedente_attesa = riga.entry_hash
            numero_atteso = riga.seq + 1

        if len(righe) < blocco:
            break

    return esito
