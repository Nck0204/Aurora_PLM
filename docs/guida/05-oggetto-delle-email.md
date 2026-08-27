# L'oggetto delle email

Aurora archivia da sola la corrispondenza con i clienti e la attacca alla
versione di prodotto di cui parla. Per riuscirci deve capire **di che cosa
parla un messaggio**, e l'unica cosa che ha per capirlo e' l'oggetto.

Questa pagina dice come si scrive un oggetto che si archivia da solo. Sono due
minuti di lettura che valgono un messaggio in quarantena in meno alla settimana.

## Come si scrive un oggetto che Aurora capisce

La forma completa e' questa:

```
RMS1100-24-110SW v2 [OFF] Offerta per la fornitura di 50 pezzi
```

Quattro pezzi, e solo il primo e' obbligatorio.

**Il codice prodotto.** `RMS1100-24-110SW`. E' quello che dice a quale prodotto
appartiene il messaggio. Senza, Aurora non ha nessun modo di indovinarlo se non
guardando le risposte a un messaggio gia' archiviato.

**La versione.** `v2`, oppure `rev2`, oppure `versione 2`. Se manca, il
messaggio va sulla versione **piu' recente** di quel prodotto, che quasi sempre
e' quella giusta ma non sempre.

**Il motivo, fra parentesi quadre.** `[OFF]` per un'offerta, `[ORD]` per un
ordine, `[MOD]` per una richiesta di modifica. L'elenco dei motivi lo decide
l'azienda e si amministra dalla pagina della posta: se ne serve uno nuovo, si
aggiunge li'.

**Il resto**, che e' l'oggetto vero e proprio, scritto per le persone.

## Le risposte non hanno bisogno di niente

Un `Re:` a un messaggio gia' archiviato finisce **dove e' finito quello a cui
risponde**, anche se l'oggetto e' stato riscritto da capo. Aurora segue la
catena delle risposte come la segue un programma di posta.

Quindi la regola pratica e' una sola: **il codice va scritto nel primo
messaggio di una conversazione.** Da li' in poi funziona tutto da solo.

## Che cosa succede quando l'oggetto non basta

Il messaggio viene archiviato lo stesso - non si perde mai niente - e finisce
in **quarantena**, cioe' in attesa che una persona dica a quale versione
appartiene. Non e' un errore: e' il funzionamento normale per tutti i messaggi
che Aurora non riesce ad attribuire da sola.

Vedi: [Messaggi in quarantena](/aiuto/messaggi-in-quarantena).

## Gli errori piu' frequenti

**Il codice scritto a meta'.** `RMS1100` invece di `RMS1100-24-110SW`. Aurora
cerca un prodotto con quel codice esatto: se non lo trova, quarantena.

**Il codice di un prodotto che non esiste ancora in Aurora.** Capita con le
richieste di offerta per apparecchi nuovi. E' normale, e la quarantena e'
esattamente il posto giusto in cui devono finire finche' il prodotto non viene
creato.

**Una versione che non c'e'.** `v7` di un prodotto che ha tre versioni. Aurora
non "arrotonda" alla piu' vicina: mette in quarantena, perche' attaccare il
messaggio a una versione a caso sarebbe peggio che non attaccarlo.

**Il codice dentro il corpo del messaggio invece che nell'oggetto.** Aurora
guarda solo l'oggetto. Il corpo si puo' cercare a mano dalla pagina della
posta, ma l'attribuzione automatica passa da li'.

## Che cosa Aurora non fa mai

**Non cancella niente dalla casella** e non segna niente come letto. Un
messaggio archiviato viene **spostato** in una cartella `Elaborate` o
`Quarantena`: se lo si cerca nella posta in arrivo e non c'e' piu', e' li'.

Lo stato di lettura appartiene a chi usa quella casella, e Aurora non e' il suo
programma di posta.
