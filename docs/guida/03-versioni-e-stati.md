# Versioni e stati

In Aurora la parola "versione" vuol dire due cose diverse, e la parola "stato"
anche. Questa pagina serve a non confonderle.

## Due versioni diverse

**La versione di un prodotto** e' una revisione dell'apparecchio: la versione 2
di `RMS1100-24-110SW` e' lo stesso prodotto con qualcosa di cambiato dentro. Le
versioni si possono **derivare** l'una dall'altra, e Aurora tiene il conto di
chi discende da chi.

**La versione di un documento** e' una revisione di un file: la revisione 3
dello schema elettrico. Sta dentro un documento, che sta dentro un progetto,
che sta sopra una versione di prodotto.

Sono due numerazioni indipendenti. La revisione 3 di uno schema non ha niente a
che vedere con la versione 3 del prodotto.

## Una versione e' un fatto avvenuto

Vale per tutte e due. Una versione caricata o creata **non si modifica e non si
sostituisce**: si crea quella dopo.

E' la regola che rende Aurora utile in sede di verifica. Se una revisione
potesse essere riscritta, nessuna revisione dimostrerebbe piu' niente: davanti
a un cliente che chiede quale schema fosse in vigore a marzo, la risposta
sarebbe "quello che c'e' adesso nella casella di marzo", che non e' una
risposta.

## Il ciclo di vita di una versione di prodotto

Sono cinque stati, e si attraversano in un ordine.

| Stato | Che cosa vuol dire |
|---|---|
| in sviluppo | ci si sta lavorando. E' lo stato di partenza |
| rilasciato | approvata: si puo' produrre |
| in produzione | e' quella che si sta costruendo adesso |
| superato | c'e' una versione piu' nuova che ha preso il suo posto |
| obsoleto | non si usa piu' e non si deve piu' usare |

**Il superamento e' automatico.** Quando una versione entra in produzione,
quella che c'era prima diventa "superata" da sola: e' l'unica cosa che il
programma decide senza chiedere, e la fa perche' dimenticarsene e' la
dimenticanza piu' facile e piu' costosa che ci sia.

Non tutti i passaggi sono possibili. Da "obsoleto" non si torna indietro: se
serve di nuovo qualcosa che era stato dichiarato obsoleto, se ne fa una
versione nuova.

## Gli stati di un documento

Sono quattro e raccontano un'altra storia: non la vita del prodotto, il
cammino di un foglio verso l'approvazione.

| Stato | Che cosa vuol dire |
|---|---|
| bozza | ci si sta lavorando. Si puo' caricare, correggere, ritirare |
| in verifica | qualcuno lo sta controllando |
| rilasciato | approvato. **Da qui in poi non si tocca piu'** |
| superato | c'e' una revisione piu' nuova |

**"Rilasciato" e' un punto di non ritorno.** Su un documento rilasciato non si
carica piu' niente e non si cambia piu' niente: se serve una correzione, si
carica una revisione nuova, che nasce in bozza e rifa' il giro.

**"Rilasciato" e "superato" hanno lo stesso colore** degli stati omonimi di una
versione di prodotto. Non e' un caso: vogliono dire la stessa cosa, e dargliene
uno diverso insegnerebbe che il verde di questa pagina non e' il verde di
quell'altra.

## Chi puo' cambiare uno stato

Non tutti, e dipende dal progetto e dalla classificazione del documento. Il
pulsante compare solo a chi puo' premerlo: se non lo vedi, non e' nascosto, e'
che quel passaggio non spetta a te.

Vedi anche: [Chi vede che cosa](/aiuto/chi-vede-che-cosa).
