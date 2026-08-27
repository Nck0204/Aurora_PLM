# Messaggi in quarantena

## Che cos'e' la quarantena

E' l'elenco dei messaggi che Aurora ha archiviato ma non e' riuscita ad
attribuire a una versione di prodotto. Sono al sicuro, sono cercabili, e
aspettano che una persona dica a chi appartengono.

**Un messaggio in quarantena non e' un messaggio perso e non e' un errore.**
La regola di Aurora sulla posta e' "mai scartare, mai bloccarsi": un messaggio
che il programma non capisce e' comunque un messaggio che l'azienda ha
ricevuto, e buttarlo via perche' l'oggetto era scritto male sarebbe il peggiore
dei comportamenti possibili.

## Perche' un messaggio ci finisce

La pagina lo dice, messaggio per messaggio. I motivi sono cinque.

| Motivo | Che cosa vuol dire |
|---|---|
| nessun codice prodotto | nell'oggetto non c'era niente di riconoscibile |
| prodotto sconosciuto | il codice c'era ma in Aurora quel prodotto non esiste |
| versione inesistente | l'oggetto dichiarava `v7` e le versioni sono tre |
| file illeggibile | il messaggio e' arrivato troncato o rovinato |
| conversazione sconosciuta | e' una risposta a un messaggio mai archiviato |

## Che cosa fare

Si apre **Posta > Quarantena**, si apre il messaggio, si legge, e si sceglie a
quale versione di prodotto appartiene.

**Se e' una conversazione, si assegnano tutti insieme.** Assegnando un
messaggio, Aurora propone di assegnare allo stesso posto anche gli altri
messaggi della stessa catena di risposte: quasi sempre e' quello che si vuole,
e farlo uno per uno su una discussione di quindici messaggi e' il modo di
smettere di usare la quarantena.

**Se il prodotto non esiste ancora**, prima si crea il prodotto e poi si
assegna. Non c'e' fretta: il messaggio resta li'.

**Se non appartiene a nessun prodotto** - una circolare, una comunicazione
amministrativa - si lascia in quarantena. Non c'e' un modo di cancellarlo, e
va bene cosi': occupa pochi byte e un giorno qualcuno potrebbe cercarlo.

## Chi puo' vedere e chi puo' assegnare

**Vedere la quarantena e assegnare i messaggi e' riservato a chi amministra
Aurora.** La ragione e' che un messaggio in quarantena non e' ancora attaccato
a nessun progetto: finche' non lo e', non c'e' nessuna regola che dica chi lo
puo' leggere, e l'unica scelta prudente e' che lo legga chi ha gia' accesso a
tutto.

Dal momento in cui viene assegnato, invece, il messaggio segue **la stessa
identica regola di un documento**: e' un documento di classificazione
"Corrispondenza" nel progetto di quella versione, e lo vede chi vede quella
classificazione.

## Se la quarantena si riempie

Venti messaggi in attesa cominciano a essere tanti, e la pagina di diagnostica
lo segnala in giallo. Non e' un guasto - i messaggi non si perdono e non
scadono - ma vuol dire che nessuno li sta smistando, e ogni giorno che passa la
coda e' piu' lunga da smaltire.

Se la coda cresce sempre, di solito il rimedio non e' smaltirla piu' in fretta:
e' far scrivere meglio gli oggetti. Vedi
[L'oggetto delle email](/aiuto/oggetto-delle-email).
