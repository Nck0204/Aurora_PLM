"""Come si chiama un oggetto quando lo si nomina dentro una frase.

Un solo mestiere: prendere una riga del database e restituire il nome con cui
una persona la chiamerebbe parlando. Un progetto non si chiama
"9d3f1a2c-...", si chiama "RMS1100-24-110SW v2"; un cliente non si chiama con
il suo identificatore, si chiama "FNM - Ferrovie Nord Milano".

**Perche' un file a se'.** Serve al registro delle operazioni, che di ogni
voce scrive una descrizione in italiano (sessione 9), e serve a chi la voce la
scrive - cioe' a mezzo programma. Se queste funzioni stessero dentro uno dei
servizi, gli altri servizi dovrebbero importarlo, e siccome projects importa
gia' phases si tornerebbe subito a due moduli che si importano a vicenda. Qui
dentro si importano solo i modelli, quindi lo puo' importare chiunque.

**Non decide niente e non interroga niente.** Sono funzioni pure sui campi
degli oggetti che riceve. L'unica cosa a cui stare attenti e' che alcune
attraversano un collegamento (un progetto arriva alla sua versione, che arriva
al suo prodotto): se l'oggetto e' stato caricato senza quei collegamenti,
leggere il nome costa un'interrogazione in piu'. Va bene dove le usiamo -
subito dopo un'operazione di scrittura, quando quegli oggetti sono gia' in
memoria - e non va bene dentro un ciclo su mille righe.
"""

from app.models import (
    Classification,
    Contact,
    Customer,
    Document,
    PhaseTemplate,
    Product,
    ProductVersion,
    Project,
    User,
)


def nome_utente(utente: User) -> str:
    """Il nome utente. E' quello con cui le persone si chiamano fra loro."""
    return utente.username


def nome_cliente(cliente: Customer) -> str:
    """Sigla e ragione sociale: la sigla si cerca, il nome si riconosce."""
    return f"{cliente.code} - {cliente.name}"


def nome_contatto(contatto: Contact) -> str:
    """Nome e posta elettronica: due contatti omonimi capitano davvero."""
    if contatto.email:
        return f"{contatto.name} <{contatto.email}>"
    return contatto.name


def nome_prodotto(prodotto: Product) -> str:
    """Il codice parlante. La descrizione e' lunga e non identifica niente."""
    return prodotto.code


def nome_versione(versione: ProductVersion) -> str:
    """Codice del prodotto e numero di versione: "RMS1100-24-110SW v2"."""
    return f"{versione.product.code} v{versione.version_number}"


def nome_progetto(progetto: Project) -> str:
    """Un progetto si chiama con la versione su cui e' aperto.

    E' la stessa forma che compare nel titolo della sua scheda: chi legge il
    registro e poi apre la pagina deve ritrovare la stessa scritta, altrimenti
    deve fermarsi a capire se sta guardando la stessa cosa.
    """
    return nome_versione(progetto.product_version)


def nome_documento(documento: Document) -> str:
    """Il titolo del documento, che e' quello che si legge negli elenchi."""
    return documento.title


def nome_classificazione(classificazione: Classification) -> str:
    """Il nome della classificazione: "Tecnico", "Commerciale"."""
    return classificazione.name


def nome_modello_fasi(modello: PhaseTemplate) -> str:
    """Nome e versione del modello: i modelli sono versionati e immutabili."""
    return f"{modello.name} v{modello.version}"
