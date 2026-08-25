"""La vetrina dei componenti grafici. Riservata al creatore.

    GET /stile                   tutti i componenti, in tutte le varianti
    GET /stile/esempio-ricerca   il pezzo di pagina che HTMX va a prendere

**A che cosa serve.** E' il riferimento di tutte le sessioni successive: chi
deve costruire una pagina nuova apre questa, guarda com'e' fatto il componente
che gli serve, copia la riga d'esempio e va avanti. Serve anche a scoprire
subito che una modifica al foglio di stile ha rotto qualcosa: se dopo un
ritocco alla variabile del bordo qui c'e' un riquadro storto, si e' visto in
tre secondi invece che tre pagine dopo.

**Perche' e' riservata al creatore.** Non contiene niente di riservato: e' una
pagina di esempi. Ma e' uno strumento di chi sviluppa, non di chi usa Aurora,
e in mezzo alle sezioni vere confonderebbe soltanto. Chi ha bisogno di
guardarla ha il ruolo per farlo.

**Non ha dati veri.** Tutto quello che si vede qui e' inventato dentro questo
file. Nessuna interrogazione al database: la vetrina deve aprirsi anche il
giorno in cui il database non risponde, che e' proprio uno dei giorni in cui
si guarda una pagina di diagnostica.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from app.dependencies import richiedi_creatore
from app.templating import pagina

# La dipendenza sta sul router: vale per tutte le rotte qui dentro, comprese
# quelle che qualcuno aggiungera' domani.
router = APIRouter(
    prefix="/stile",
    tags=["stile"],
    dependencies=[Depends(richiedi_creatore)],
)


# Righe finte per gli esempi di tabella e di ricerca. Hanno la forma dei dati
# veri della sessione 5 (codice parlante, descrizione, cliente, stato) ma non
# vengono da nessuna parte: sono scritte qui.
PRODOTTI_DI_ESEMPIO: tuple[dict[str, str], ...] = (
    {
        "codice": "SCH-A100-R02",
        "descrizione": "Scheda di controllo motore, revisione 2",
        "cliente": "Meccanica Bianchi",
        "stato": "in_produzione",
        "versione": "2.1",
    },
    {
        "codice": "SCH-A100-R03",
        "descrizione": "Scheda di controllo motore, revisione 3",
        "cliente": "Meccanica Bianchi",
        "stato": "in_sviluppo",
        "versione": "3.0",
    },
    {
        "codice": "ALI-B220-R01",
        "descrizione": "Alimentatore 24V 60W",
        "cliente": "Impianti Ferrari",
        "stato": "rilasciato",
        "versione": "1.4",
    },
    {
        "codice": "SEN-C310-R01",
        "descrizione": "Sensore di temperatura industriale",
        "cliente": "Termotecnica Rossi",
        "stato": "superato",
        "versione": "1.0",
    },
    {
        "codice": "CAV-D050-R00",
        "descrizione": "Cablaggio quadro comandi",
        "cliente": "Impianti Ferrari",
        "stato": "obsoleto",
        "versione": "0.9",
    },
)


def cerca_esempio(testo: str) -> list[dict[str, str]]:
    """Filtra le righe finte, come farebbe una ricerca vera.

    Il confronto e' senza distinzione fra maiuscole e minuscole e guarda sia
    il codice sia la descrizione: e' il comportamento che ci si aspetta da una
    casella di ricerca, ed e' quello che le sessioni successive dovranno
    riprodurre sul database.
    """
    if not testo.strip():
        return list(PRODOTTI_DI_ESEMPIO)

    cercato = testo.strip().lower()
    return [
        riga
        for riga in PRODOTTI_DI_ESEMPIO
        if cercato in riga["codice"].lower()
        or cercato in riga["descrizione"].lower()
    ]


@router.get("")
def vetrina(
    request: Request,
    q: str = "",
    ordina: str = "codice",
    verso: str = "asc",
    pagina_numero: int = 1,
) -> Response:
    """Mostra tutti i componenti, in tutte le varianti.

    I parametri servono agli esempi vivi: la ricerca filtra davvero le righe
    finte, l'ordinamento le riordina davvero, l'impaginazione mostra davvero
    la pagina scelta. Un esempio che non funziona insegna la cosa sbagliata.
    """
    righe = cerca_esempio(q)
    righe.sort(
        key=lambda riga: riga.get(ordina, riga["codice"]),
        reverse=(verso == "desc"),
    )

    return pagina(
        request,
        "stile.html",
        q=q,
        ordina=ordina,
        verso=verso,
        pagina_numero=pagina_numero,
        righe=righe,
    )


@router.get("/esempio-ricerca")
def esempio_ricerca(request: Request, q: str = "") -> Response:
    """Il pezzo di pagina che HTMX sostituisce mentre si scrive nella casella.

    E' l'unico posto della sessione 4 in cui HTMX fa davvero qualcosa, e serve
    a verificare che il file scaricato in app/static/vendor/ funzioni.

    **Il modulo funziona anche senza.** La casella di ricerca della vetrina e'
    un normale modulo GET che punta a /stile: con JavaScript spento si preme
    Invio e la pagina si ricarica filtrata. HTMX si limita a sostituire il
    pezzo di tabella senza ricaricare tutto. E' cosi' che va usato dappertutto
    in Aurora: come un miglioramento, mai come la condizione perche' qualcosa
    funzioni.
    """
    return pagina(
        request,
        "stile_risultati.html",
        q=q,
        righe=cerca_esempio(q),
    )
