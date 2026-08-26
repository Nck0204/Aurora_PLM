# Guida allo stile

Come si costruisce una pagina di Aurora. Va letta prima di scrivere il primo
template di una sessione nuova.

La regola che riassume tutte le altre: **i componenti ci sono gia'**. Stanno in
`app/templates/components/`, si vedono tutti insieme all'indirizzo `/stile`, e
non se ne inventano di nuovi senza aggiungerli li'. Un programma in cui ogni
sessione si porta dietro il proprio pulsante e' un programma che dopo tredici
sessioni ha tredici pulsanti diversi.

- Il foglio di stile: `app/static/css/aurora.css`, uno solo, scritto a mano.
- I componenti: `app/templates/components/`, un file per famiglia.
- La vetrina: `/stile`, visibile a chi ha il ruolo di creatore.

---

## 1. Direzione visiva

Tema scuro, tecnico, professionale. Deve trasmettere precisione e
affidabilita': non e' un programma allegro, e' uno strumento che degli
ingegneri useranno tutto il giorno accanto ad altri strumenti scuri.

Densita' informativa alta, ma con abbastanza respiro da poterci stare otto ore.
In pratica vuol dire: righe compatte nelle tabelle, margini generosi fra i
blocchi, un solo pulsante colorato per pagina.

Il tema e' uno solo e non si cambia (decisione D-003).

---

## 2. Palette

Tutti i colori sono variabili CSS dichiarate in `:root`, in cima ad
`aurora.css`. Nel resto del programma si richiamano con `var(--nome)`: **dentro
un componente non si scrive mai un valore esadecimale**, e c'e' un test che lo
verifica (`tests/test_interfaccia.py`).

### Superfici, dalla piu' profonda alla piu' vicina

| Variabile | Valore | Dove si usa |
|---|---|---|
| `--colore-sfondo` | `#0B0E14` | la tela su cui poggia tutto |
| `--colore-superficie` | `#141821` | riquadri, barre, tabelle |
| `--colore-superficie-sollevata` | `#1B2130` | quello che sta sopra un riquadro: pulsanti, intestazioni di tabella |
| `--colore-superficie-passaggio` | `#212939` | la stessa superficie sotto il mouse |
| `--colore-riga-alterna` | `#171C26` | le righe pari di una tabella |

### Bordi

| Variabile | Valore | Dove si usa |
|---|---|---|
| `--colore-bordo` | `#262D3D` | il bordo normale |
| `--colore-bordo-tenue` | `#1E2432` | i separatori dentro un riquadro |
| `--colore-bordo-marcato` | `#38415A` | il campo sotto il mouse, la riga scelta |

### Testo e tinte di servizio

| Variabile | Valore | Dove si usa |
|---|---|---|
| `--colore-testo` | `#E6EAF2` | il testo normale |
| `--colore-testo-tenue` | `#8B94A7` | spiegazioni, etichette di colonna, note |
| `--colore-testo-su-accento` | `#0B0E14` | il testo scuro sopra una tinta piena |
| `--colore-accento` | `#5B9DFF` | l'azione principale, i collegamenti |
| `--colore-accento-scuro` | `#3D7FE0` | l'accento premuto |
| `--colore-successo` | `#3FB950` | e' andata bene |
| `--colore-attenzione` | `#D29922` | guarda prima di premere |
| `--colore-errore` | `#F85149` | non e' andata |

### Stati del ciclo di vita

Sono i cinque valori di `LifecycleState` (`app/models/enums.py`). La
corrispondenza fra stato e tinta e' fissata una volta sola: **lo stesso stato ha
lo stesso colore in ogni pagina, per sempre.** Ogni stato ha una tinta (per il
testo e il bordo) e un fondo appena tinto.

| Stato | Tinta | Fondo |
|---|---|---|
| in sviluppo | `--stato-in-sviluppo` `#5B9DFF` | `--stato-in-sviluppo-fondo` `#1C283C` |
| rilasciato | `--stato-rilasciato` `#3FB950` | `--stato-rilasciato-fondo` `#192B27` |
| in produzione | `--stato-in-produzione` `#2EA043` | `--stato-in-produzione-fondo` `#162524` |
| superato | `--stato-superato` `#D29922` | `--stato-superato-fondo` `#2B2721` |
| obsoleto | `--stato-obsoleto` `#8B94A7` | `--stato-obsoleto-fondo` `#222731` |

### Stati di un documento

Sono i quattro valori di `DocumentState`. **"Rilasciato" e "superato" prendono
apposta la stessa tinta** degli stati omonimi di una versione di prodotto:
vogliono dire la stessa cosa, e dargliene una diversa insegnerebbe che il verde
di questa pagina non e' il verde di quell'altra.

| Stato | Etichetta |
|---|---|
| bozza | quella neutra: e' il punto di partenza, non e' una notizia |
| in verifica | `--colore-attenzione`: c'e' qualcuno che deve fare qualcosa |
| rilasciato | `--stato-rilasciato`, la stessa del ciclo di vita |
| superato | `--stato-superato`, la stessa del ciclo di vita |

Nessuna classe CSS nuova: sono tutte etichette che esistevano gia'.

Non si usa mai il colore come unica informazione: dentro l'etichetta c'e'
sempre la parola scritta.

---

## 3. Spaziature, raggi, ombre, caratteri

**Spaziature.** Scala basata su 4 pixel: `--spazio-1` (4px), `-2` (8), `-3`
(12), `-4` (16), `-5` (20), `-6` (24), `-8` (32), `-10` (40), `-12` (48). Non si
usano misure fuori da questa scala. Avere nove valori invece di trenta e' quello
che tiene allineate pagine scritte in giorni diversi da persone diverse.

**Raggi.** `--raggio-piccolo` (6px) per pulsanti, campi ed etichette;
`--raggio` (10px) per riquadri, tabelle e finestre.

**Ombre.** `--ombra-1` per staccare un riquadro dal fondo, `--ombra-2` per
quello che galleggia sopra la pagina (finestre e notifiche). Su fondo scuro
servono soprattutto a dire "questa cosa sta sopra le altre".

**Caratteri.** Solo quelli gia' presenti nel sistema operativo: niente da
scaricare, niente che manchi il primo giorno.

- `--carattere`: `system-ui, "Segoe UI", Roboto, ...` per il testo;
- `--carattere-mono`: `ui-monospace, "Cascadia Mono", Consolas, ...` per i
  **codici**: codici prodotto, codici articolo, nomi utente, impronte, password
  assegnate. Li' la differenza fra `0` e `O` e fra `1` e `l` deve vedersi.

Misure del testo: `--testo-piccolo` (12), `--testo-normale` (14),
`--testo-grande` (16), `--testo-titolo` (20), `--testo-titolo-grande` (26).

**Sui valori che restano scritti per esteso.** Colori, spaziature, raggi e ombre
passano tutti dalle variabili. Le misure strutturali di un singolo componente
non lo fanno: il bordo da un pixel, il quadratino della casella di spunta da 16,
il pallino dell'avanzamento da 28. Trasformare anche quelle in variabili
riempirebbe `:root` di righe usate una volta sola e renderebbe illeggibile
proprio il posto che deve restare leggibile.

---

## 4. Convenzione dei nomi

Blocco e modificatore separati da due trattini:

```
.pulsante                il componente
.pulsante--primario      una sua variante
.pulsante--piccolo       un'altra sua variante, che si somma alla prima
```

I nomi delle classi sono **in italiano**, perche' descrivono cose che si vedono,
come i testi dell'interfaccia. Gli identificatori del codice restano in inglese
(CLAUDE.md, regola 4).

I nomi dei **macro** devono essere specifici. I macro importati da una pagina
finiscono nello stesso spazio delle variabili con cui viene disegnato anche
`base.html`: un macro chiamato `menu` copriva le voci della barra laterale, e la
pagina si apriva con un errore che non diceva niente. Per questo il menu a
tendina si chiama `tendina`.

**La stessa trappola vale dalla parte di Python.** La funzione `pagina()` ha
due parametri suoi, `nome` (il file del template) e `stato` (il codice HTTP):
passarli come variabili di contesto - per far tornare a un modulo il nome
scritto da chi lo stava compilando, per esempio - produce
`pagina() got multiple values for argument 'nome'`, che non dice niente a chi
lo legge. Si passa `nome_cliente`, `nome_prodotto`, `stato_scelto`. E' stato
scoperto nella sessione 5, ed e' scritto anche nella docstring di `pagina()`,
che e' il posto in cui si va a guardare.

---

## 5. I componenti

Stanno in `app/templates/components/`. In cima a ogni file c'e' scritto
**quando si usa e quando non si usa**: quella e' la documentazione, `/stile` e'
la prova.

| File | Macro | A che serve |
|---|---|---|
| `icone.html` | `icona` | i ventotto simboli, disegnati a mano in SVG |
| `pulsanti.html` | `pulsante`, `pulsante_collegamento`, `modulo_pulsante` | ogni azione |
| `campi.html` | `campo`, `area_testo`, `tendina`, `spunta`, `scelta`, `csrf` | ogni campo di un modulo |
| `tabella.html` | `tabella` | gli elenchi, con intestazione ferma e ordinamento |
| `tabella.html` (variante `tabella--matrice`) | — | la griglia dei permessi: intestazione su due piani, prima colonna ferma |
| `stato.html` | `etichetta_ciclo_vita`, `etichetta_documento`, `etichetta`, `etichetta_utente` | le pillole colorate degli stati |
| `riquadro.html` | `riquadro` | il contenitore di tutto |
| `dialogo.html` | `dialogo`, `pulsante_apri`, `pulsante_chiudi` | le conferme modali |
| `avvisi.html` | `avviso`, `notifica` | i messaggi, fermi o temporanei |
| `ricerca.html` | `ricerca` | la barra di ricerca, con i filtri a tendina e l'intervallo di date |
| `impaginazione.html` | `impaginazione` | le pagine di un elenco lungo |
| `schede.html` | `schede`, `scheda`, `schede_collegamento`, `schede_oggetto` | le linguette |
| `avanzamento.html` | `avanzamento` | le fasi di un progetto in fila |
| `griglia_fasi.html` | `griglia_fasi` | il modulo con cui si scrivono le fasi di un modello |
| `descrizione.html` | `descrizione`, `voce` | la scheda di dettaglio etichetta/valore |
| `area_file.html` | `area_file` | il caricamento dei documenti |
| `barra_caricamento.html` | `barra_caricamento` | quanti byte sono partiti, mentre partono |
| `vuoto.html` | `vuoto` | quando non c'e' niente da mostrare |
| `storico.html` | `storico` | le voci del registro delle operazioni |
| `messaggio.html` | `corpo_messaggio` | il testo di una mail archiviata |

### Nei template non si decide chi puo' fare che cosa

Un `{% if utente.is_creatore %}` dentro una pagina non e' una protezione: la
rotta si apre lo stesso scrivendone l'indirizzo, e intanto sembra che protegga.
Le pagine ricevono la risposta **gia' decisa** - `puo_amministrare`,
`permessi.caricare`, `puo_cambiare_stato` - e la usano soltanto per sapere se
disegnare un pulsante. Chi decide e' `permissions.puo()`, e nessun altro
(D-051, CLAUDE.md sezione 8). C'e' un test che legge tutti i template e diventa
rosso se ci ricompare `is_creatore`, `global_role` o `permission_rules`.

Vale anche per il nome di un ruolo mostrato in una pagina: non e' un permesso,
ma si compone lo stesso in Python (`users.ruolo_mostrato()`), per la regola qui
sotto e perche' cosi' nei template non resta niente che assomigli a una
verifica.

### La griglia della matrice dei permessi

`tabella--matrice` e' l'unica variante della tabella dati, e sta nella sezione
26 di `aurora.css`. Ha due cose che la tabella normale non ha: l'intestazione
su **due piani** - la classificazione sopra, i suoi tre permessi sotto - e la
prima colonna **ferma** mentre si scorre di lato, con il suo fondo opaco. Con
sei classificazioni la griglia esce dallo schermo, e una riga di spunte senza
il nome del ruolo davanti non si legge.

Le celle contengono un comando invece che un dato, ed e' il motivo per cui non
sono una tabella normale con dentro tre `spunta`: la casella di spunta dei
moduli porta con se' etichetta, aiuto e margini, che in una griglia di
trentasei quadretti sarebbero trentasei etichette di troppo. Qui l'etichetta e'
l'intestazione della colonna, e ogni casella ha il suo `aria-label` per esteso
("Ingegnere, Commerciale, visualizza").

### La griglia delle fasi di un modello

`griglia_fasi` e' il modulo con cui si scrive un modello di fasi: una riga per
fase, con il nome, la descrizione e le due spunte che ne governano il
comportamento (`da qui non si torna indietro`, `chiude il progetto`). Sta nella
sezione 27 di `aurora.css`.

Ha due cose che vale la pena di sapere prima di toccarla.

**Le righe sono dieci e fisse.** Un pulsante "aggiungi fase" avrebbe bisogno di
JavaScript, e senza JavaScript il modulo non si compilerebbe piu' (D-036). Le
righe vuote vengono saltate e il numero d'ordine lo mette il programma: chi
scrive tre fasi nelle righe 1, 3 e 6 ottiene le fasi 1, 2 e 3.

**Le spunte hanno il numero della riga dentro il nome** (`fase_blocca_3`). E'
la stessa trappola della griglia dei permessi con una medicina diversa: il
browser invia una casella di spunta solo quando e' segnata, quindi da dieci
righe con due segni arrivano due campi e non venti, e senza il numero non ci
sarebbe modo di sapere a quale riga appartengono. La griglia dei permessi la
risolve con un campo nascosto perche' le sue caselle non sono numerate; qui le
righe hanno gia' un numero, e usarlo costa meno.

Le etichette dei campi ci sono ma sono **nascoste alla vista**
(`etichetta_nascosta=true` sul macro `campo`): dieci volte "Nome della fase"
renderebbe illeggibile proprio quello che si sta cercando di leggere. Nascoste
alla vista, non alla pagina - restano collegate al campo, e i lettori di
schermo le leggono tutte. E' l'unico altro posto in cui si usa quel parametro
oltre alla casella di ricerca.

### Le linguette della scheda di un oggetto

Dalla sessione 9 ogni oggetto di Aurora - prodotto, versione, progetto,
documento, persona - ha la sua scheda e il suo **storico**, cioe' le voci del
registro delle operazioni che lo riguardano. Le due pagine si tengono insieme
con `schede_oggetto`, che disegna la striscia:

```jinja
{% from "components/schede.html" import schede_oggetto %}

{{ schede_oggetto("/prodotti/" ~ prodotto.id,
                  corrente="/prodotti/" ~ prodotto.id) }}
```

**L'ordine e' sempre lo stesso e non si cambia**: la scheda per prima, lo
storico per ultimo, e in mezzo le pagine che quel tipo di oggetto ha in piu' -
una persona ha anche "Accessi", e si passano in `altre`. Chi impara dove sta lo
storico su una pagina lo ritrova nello stesso posto su tutte le altre.

Sono linguette-collegamento e non schede nella stessa pagina, ed e' il caso da
manuale per la distinzione descritta in `components/schede.html`: lo storico e'
un elenco impaginato che va interrogato, e mandarlo insieme alla scheda
vorrebbe dire far aspettare chi voleva solo leggere un titolo. Vedi D-067.

### Le voci del registro delle operazioni

Il componente `storico.html` disegna un elenco di righe di registro, e lo usano
tutte e due le pagine che ne mostrano: `/registro` e le schede "Storico".

Una voce ha due parti. Quella che si legge sempre - quando, chi, che cosa - sta
nelle colonne della tabella. Quella che si guarda solo quando serve davvero -
i valori di prima e di dopo, l'indirizzo IP, l'impronta - sta dentro un
`<details>` che si apre riga per riga. Mettere tutto in colonne renderebbe la
tabella illeggibile; nasconderlo del tutto vorrebbe dire un registro che non
risponde alle domande per cui esiste.

**Le voci arrivano al template gia' tradotte.** Il codice azione e' gia'
diventato una frase italiana, il tipo di entita' e' gia' diventato "Documento",
l'indirizzo della scheda dell'oggetto e' gia' composto o e' `None`. Le compone
`_voce_per_la_pagina()` in `app/routers/audit.py`, ed e' la regola della
sezione qui sotto applicata a un caso in cui sarebbe stato comodo sbagliare.

### Il corpo di un messaggio di posta

`messaggio.html` disegna il testo di una mail archiviata, ed e' l'unico blocco
di Aurora che mostra **testo scritto da qualcun altro**: lungo quanto capita,
con gli a capo che contano e con righe che nessuno ha impaginato per noi. Sta
nella sezione 28 di `aurora.css`.

Tre cose che un `<pre>` non farebbe:

- **va a capo da solo.** Le mail arrivano con righe da 200 caratteri e con
  righe gia' spezzate a 72: un `<pre>` costringerebbe a scorrere di lato per
  leggere le prime;
- **non e' a spaziatura fissa.** Il corpo di una mail e' prosa, e la prosa in
  carattere da terminale si legge peggio;
- **si accorcia.** Sopra le dodici righe il resto va dentro un `<details>`:
  una mail con dentro venti risposte citate riempirebbe altrimenti sei
  schermate prima degli allegati, che sono la cosa che si stava cercando.

L'accorciamento e' un `<details>` e non JavaScript, quindi funziona anche con
JavaScript spento (D-036). Con il corpo vuoto il macro disegna la riga che lo
dice: un messaggio senza testo esiste - e' quello con il solo allegato - e la
pagina non deve sembrare rotta.

Non si usa per una frase scritta da una persona dentro Aurora (la motivazione
di un passaggio di fase, il perche' di un rifiuto): quella e' `.citazione`, che
ha la barretta a sinistra ed e' pensata per due righe.

### Gli elenchi di scelte si compongono in Python, non nei template

Le opzioni di un menu a tendina, le voci di un filtro, le coppie
(valore, etichetta) di una casella di scelta: **si costruiscono nella rotta o
nel servizio e arrivano al template gia' pronte.** Il template le disegna e
basta.

Non e' pignoleria. Un template che sa trasformare `in_sviluppo` in
"in sviluppo", o che sa mettere in fila identificatori e nomi, e' un template
che contiene una regola; e le regole scritte dentro l'HTML non si possono ne'
provare con un test ne' riusare da un'altra pagina. Nella sessione 5 le
stesse due tendine (stato del ciclo di vita, fase corrente) compaiono in due
pagine diverse e arrivano tutte e due da `projects.filtri_cruscotto()`: scritte
due volte, alla prima modifica ne sarebbe rimasta indietro una.

Dove guardare per copiare: `lifecycle.opzioni_stati()`,
`projects.filtri_cruscotto()`, `_filtri_ricerca()` in `app/routers/products.py`
- quest'ultima costruisce le tendine leggendo la configurazione, quindi il
giorno in cui la regola dei codici avra' un elemento in piu' comparira' una
tendina in piu' senza che nessuno tocchi un template.

### Le distinzioni che si sbagliano piu' spesso

**Pulsante o collegamento.** Se l'azione cambia qualcosa nel programma e' un
`<button>` dentro un modulo POST, con il suo gettone CSRF. Se porta soltanto da
un'altra parte e' un collegamento. Non e' formalismo: un collegamento lo puo'
far scattare chiunque, anche una pagina ostile.

**Avviso o notifica.** Se il messaggio serve a capire che cosa fare adesso, e'
un avviso in linea e resta li'. Se e' soltanto la conferma di qualcosa che
l'utente ha appena fatto e ha gia' visto succedere, e' una notifica temporanea.
Non si mette mai in una notifica un errore su cui si deve agire: le notifiche
spariscono.

**Tabella vuota o riquadro vuoto.** Se l'elenco esiste ed e' solo filtrato, si
usa la riga vuota dentro la tabella: togliere la tabella farebbe sparire anche i
filtri, e nessuno saprebbe piu' che cosa cambiare. Se non c'e' proprio niente
perche' non e' mai stato creato niente, si usa il riquadro vuoto, che spiega e
propone l'azione.

**Finestra modale o pagina.** Se la finestra non si aprisse, l'utente
resterebbe bloccato? Allora non e' una finestra, e' una pagina.

---

## 6. Struttura di una pagina

`base.html` da' l'impalcatura: barra laterale a sinistra, barra superiore in
cima, area del contenuto, contenitore delle notifiche. Una pagina figlia riempie
quattro blocchi:

```jinja
{% extends "base.html" %}

{% block titolo %}Utenti{% endblock %}          {# la finestra del browser #}
{% block sezione %}Utenti{% endblock %}         {# la barra superiore #}
{% block contenuto %}...{% endblock %}          {# il corpo #}
{% block notifiche %}...{% endblock %}          {# gli esiti temporanei #}
```

`base_nudo.html` e' l'impalcatura senza impalcatura: niente barra laterale,
contenuto centrato. Serve alle pagine di chi non e' dentro il programma -
l'accesso e gli errori.

**La barra laterale non si scrive nel template.** Le voci stanno in
`app/navigation.py`, gia' filtrate per ruolo. Quando una sezione viene
realizzata si toglie `attiva=False` dalla sua voce: la barra si aggiorna da sola
in tutte le pagine. Nascondere una voce non protegge niente - il lucchetto e'
la dipendenza dichiarata sulla rotta.

**Ogni modulo POST porta il gettone.** `{{ csrf(request) }}` come prima riga
dentro il `<form>`, altrimenti la richiesta viene rifiutata con un 400 (D-028).

**L'errore di un modulo rifiutato lo disegna `base.html`, non la pagina.** Una
rotta che chiama `pagina(..., errore="...")` ha gia' finito: l'avviso rosso
compare in cima al contenuto. Riscriverlo dentro la pagina lo fa comparire due
volte, ed e' un difetto che e' passato inosservato in tre template fino alla
sessione 8, perche' due avvisi identici uno sotto l'altro si leggono come uno.

Una pagina che l'avviso lo debba comporre da se' - perche' ci va dentro un
pulsante, come il divieto di tornare indietro che offre di creare una versione
nuova di prodotto - **non usa il nome `errore`**: la rotta le passa il
messaggio con un altro nome (`problema`), e la pagina se lo disegna.

---

## 7. Accessibilita'

Non sono buone intenzioni: sono cose verificate da `tests/test_interfaccia.py`.

**Contrasto.** Nessuna combinazione di testo e fondo scende sotto 4.5:1.
Misurato:

| testo | su sfondo | su superficie | su sollevata |
|---|---|---|---|
| `--colore-testo` | 16.02:1 | 14.73:1 | 13.33:1 |
| `--colore-testo-tenue` | 6.34:1 | 5.83:1 | 5.27:1 |
| `--colore-accento` | 7.09:1 | 6.52:1 | 5.90:1 |
| `--colore-successo` | 7.60:1 | 6.99:1 | 6.33:1 |
| `--colore-attenzione` | 7.65:1 | 7.04:1 | 6.37:1 |
| `--colore-errore` | 5.76:1 | 5.30:1 | 4.79:1 |

Le etichette di stato, ciascuna sulla propria tinta di fondo: in sviluppo
5.44:1, rilasciato 5.84:1, in produzione 4.70:1, superato 5.88:1, obsoleto
4.91:1. I pulsanti: primario 7.09:1, pericolo 5.76:1, secondario 13.33:1.

**Etichette.** Ogni campo ha la sua `<label for="...">` collegata. Non si usano
segnaposto al posto delle etichette: spariscono appena si comincia a scrivere.
Dove l'etichetta non serve alla vista (la casella di ricerca) c'e' comunque,
nascosta con `.solo-lettura-vocale`.

**Tastiera.** Il fuoco si vede sempre: due pixel di accento, mai tolti. Il primo
collegamento di ogni pagina e' "Salta al contenuto", che compare quando riceve
il fuoco e permette di scavalcare la barra laterale. Le voci di menu spente sono
`<span>` e non `<a>`: la tastiera non ci si ferma, perche' non c'e' niente da
aprire.

**Il colore non e' mai l'unica informazione.** Gli stati hanno la parola
scritta, gli avvisi hanno l'icona, la voce di menu corrente ha una barretta
oltre al colore, le fasi concluse hanno una spunta e non solo il verde.

**Chi ha chiesto meno animazioni** (`prefers-reduced-motion`) non ne vede
nessuna.

---

## 8. Larghezza dello schermo

Aurora si usa su schermi da scrivania. Sopra i 1280 pixel la barra laterale
mostra icone e testo; sotto, si stringe a sole icone (60 pixel) e i nomi
restano come suggerimento del mouse e per i lettori di schermo.

Piu' sotto di cosi' non si scende. Non e' un programma da telefono, e fingere
che lo sia costerebbe lavoro a ogni pagina per un uso che non esiste.

---

## 9. JavaScript

Tre file, tutti serviti da noi (regola 1 di CLAUDE.md):

| File | A che serve |
|---|---|
| `static/vendor/htmx.min.js` | HTMX 2.0.10, per aggiornare pezzi di pagina |
| `static/js/aurora.js` | notifiche, finestre di dialogo, trascinamento file, barra di avanzamento del caricamento |
| `static/js/copia.js` | il pulsante che copia la password assegnata |

**Niente di quello che c'e' dentro e' indispensabile.** Con JavaScript spento
Aurora funziona: si entra, si cambia la password, si crea un utente, si carica
un documento. Le notifiche restano finche' non si cambia pagina, le finestre
modali non si aprono (e le operazioni che contano non stanno li' dentro), i file
si scelgono con il pulsante invece che trascinandoli, e la barra
dell'avanzamento non compare - il modulo si invia da solo, come ha sempre fatto
un modulo.

Un solo posto usa `XMLHttpRequest` invece di `fetch()`, ed e' la barra del
caricamento: `fetch()` non sa dire quanti byte ha spedito, e l'avanzamento in
salita non fa parte della sua interfaccia. E' l'unica cosa di Aurora in cui la
libreria vecchia fa qualcosa che la nuova non sa fare.

HTMX si usa **come un miglioramento, mai come la condizione perche' qualcosa
funzioni**. Il modello e' la barra di ricerca: e' un modulo GET che funziona da
solo, e gli attributi `hx-` si limitano a sostituire il pezzo di tabella senza
ricaricare tutto.

Le risposte HTMX sono pezzi di pagina senza `<html>` e senza `<body>`: si
scrivono come `stile_risultati.html`.

---

## 10. Aggiungere un componente

1. Un file in `app/templates/components/`, con in cima **quando si usa e quando
   non si usa**.
2. Le sue regole in `aurora.css`, in una sezione nuova, con il numero aggiunto
   all'indice in cima al file.
3. Nessun colore scritto per esteso: solo `var(--nome)`.
4. Un esempio in `/stile`, nella scheda giusta, che passa dal macro e non
   riscrive l'HTML a mano.
5. Una riga nella tabella della sezione 5 di questa guida.

Se un componente non e' in vetrina, non lo trovera' nessuno e verra' riscritto
da capo alla prossima sessione.
