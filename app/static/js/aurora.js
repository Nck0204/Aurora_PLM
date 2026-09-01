/* ==========================================================================
   Aurora - il poco JavaScript che serve all'interfaccia.

   Scritto a mano, servito dal nostro server, nessuna libreria e nessuna
   compilazione (regole 1 e 2 di CLAUDE.md). Si occupa di tre cose sole:

     1. le notifiche temporanee, che devono sparire da sole;
     2. le finestre di dialogo, che devono aprirsi e chiudersi;
     3. l'area di trascinamento dei file, che deve accorgersi del
        trascinamento;
     4. la barra di avanzamento del caricamento, che deve dire a che punto
        sono i byte partiti.

   REGOLA CHE VALE PER TUTTO QUESTO FILE. Niente di quello che c'e' qui dentro
   e' indispensabile. Con JavaScript spento - o quando questo file non arriva
   perche' e' rimasto in una cache sbagliata - Aurora continua a funzionare:
   le notifiche restano finche' non si cambia pagina, le finestre modali non
   si aprono (e le operazioni che contano non stanno li' dentro), i file si
   scelgono con il pulsante invece che trascinandoli.

   Se un giorno qualcosa di necessario finisse qui, sarebbe un errore da
   correggere, non una scelta.

   COME SI AGGANCIA. Sempre con un attributo data-qualcosa nel template, mai
   con una classe del foglio di stile. Le classi servono all'aspetto e prima o
   poi qualcuno le rinomina: se lo script ci si appoggia, smette di funzionare
   in silenzio.
   ========================================================================== */

(function () {
    "use strict";

    /* ----------------------------------------------------------------------
       1. Notifiche temporanee

       Ogni notifica dichiara da sola quanto deve restare, nell'attributo
       data-durata (in millisecondi). Con durata 0 non sparisce: si usa per i
       messaggi lunghi da leggere.

       Il contenitore e' fisso in base.html, quindi le notifiche possono
       arrivare anche dopo, dentro un pezzo di pagina sostituito da HTMX. Per
       questo l'ascolto e' sul contenitore e non sulle singole notifiche:
       cosi' vale anche per quelle che ancora non esistono.
       -------------------------------------------------------------------- */

    var DURATA_USCITA = 200;  /* deve bastare all'animazione del CSS */

    function chiudiNotifica(notifica) {
        notifica.classList.add("notifica--in-uscita");
        window.setTimeout(function () {
            if (notifica.parentNode) {
                notifica.parentNode.removeChild(notifica);
            }
        }, DURATA_USCITA);
    }

    function programmaChiusura(notifica) {
        if (notifica.dataset.chiusuraProgrammata) {
            return;
        }
        notifica.dataset.chiusuraProgrammata = "si";

        var durata = parseInt(notifica.getAttribute("data-durata"), 10);
        if (!durata || durata <= 0) {
            return;
        }
        window.setTimeout(function () {
            chiudiNotifica(notifica);
        }, durata);
    }

    function preparaNotifiche(radice) {
        var notifiche = radice.querySelectorAll(".notifica");
        for (var i = 0; i < notifiche.length; i++) {
            programmaChiusura(notifiche[i]);
        }
    }

    var contenitoreNotifiche = document.getElementById("notifiche");
    if (contenitoreNotifiche) {
        preparaNotifiche(document);

        /* La crocetta di chiusura. L'ascolto sta sul contenitore: funziona
           anche per le notifiche aggiunte dopo. */
        contenitoreNotifiche.addEventListener("click", function (evento) {
            var chiudi = evento.target.closest(".notifica .chiudi");
            if (chiudi) {
                chiudiNotifica(chiudi.closest(".notifica"));
            }
        });

        /* Quando HTMX sostituisce un pezzo di pagina, le notifiche che
           arrivano con la risposta vanno programmate anche loro. L'evento
           esiste solo se HTMX e' stato caricato; se non c'e', questa riga non
           fa niente e non da' fastidio a nessuno. */
        document.body.addEventListener("htmx:afterSwap", function (evento) {
            preparaNotifiche(evento.target);
        });
    }

    /* ----------------------------------------------------------------------
       2. Finestre di dialogo

       Si appoggiano all'elemento <dialog> del browser, che porta gia' dentro
       il fuoco della tastiera, ce lo tiene, chiude con Esc e lo restituisce a
       chi aveva aperto. Qui si aggiungono soltanto due cose: il pulsante che
       apre (data-apre="identificatore") e quello che chiude (data-chiude).

       Il clic sullo sfondo scuro chiude anche lui. E' l'unico punto in cui
       serve un piccolo trucco: il bersaglio del clic sullo sfondo e' il
       <dialog> stesso, perche' lo sfondo (::backdrop) non e' un elemento su
       cui si possa ascoltare.
       -------------------------------------------------------------------- */

    document.addEventListener("click", function (evento) {
        var apri = evento.target.closest("[data-apre]");
        if (apri) {
            var finestra = document.getElementById(apri.getAttribute("data-apre"));
            if (finestra && typeof finestra.showModal === "function") {
                finestra.showModal();
            }
            return;
        }

        var chiudi = evento.target.closest("[data-chiude]");
        if (chiudi) {
            var daChiudere = chiudi.closest("dialog");
            if (daChiudere) {
                daChiudere.close();
            }
            return;
        }

        /* Clic sullo sfondo: il bersaglio e' il <dialog>, non il suo
           contenuto. */
        if (evento.target.tagName === "DIALOG") {
            evento.target.close();
        }
    });

    /* ----------------------------------------------------------------------
       2-bis. La domanda prima di un'azione

       Un modulo con data-conferma="Testo della domanda" chiede conferma prima
       di partire. Lo scrive il macro modulo_pulsante di
       templates/components/pulsanti.html.

       PERCHE' STA QUI E NON DENTRO LA PAGINA. Fino alla sessione 13 ogni
       pulsante con conferma si portava dietro un <script> scritto dentro
       l'HTML. La politica dei contenuti introdotta in quella sessione
       (Content-Security-Policy, app/main.py) vieta gli script in linea: quelli
       sarebbero stati bloccati dal browser, e la domanda sarebbe sparita senza
       che nessuno se ne accorgesse. Qui invece e' un file servito da noi, che
       la politica ammette, ed e' scritto una volta sola invece che una per
       pulsante.

       L'ascolto e' sul documento e in fase di cattura: cosi' vale anche per i
       moduli che arrivano dopo dentro un pezzo di pagina sostituito da HTMX,
       e la domanda si fa prima di qualunque altro gestore dell'invio.

       SENZA JAVASCRIPT LA DOMANDA NON COMPARE E L'AZIONE SI ESEGUE. E' voluto
       e non e' cambiato: nessuna delle azioni di Aurora e' irreparabile,
       perche' non si cancella niente (regola 5 di CLAUDE.md).
       -------------------------------------------------------------------- */

    document.addEventListener("submit", function (evento) {
        var modulo = evento.target;
        if (!modulo || !modulo.hasAttribute || !modulo.hasAttribute("data-conferma")) {
            return;
        }
        if (!window.confirm(modulo.getAttribute("data-conferma"))) {
            evento.preventDefault();
        }
    }, true);

    /* ----------------------------------------------------------------------
       3. Area di trascinamento dei file

       Il campo <input type="file"> c'e' gia' e funziona da solo. Qui si
       aggiunge il trascinamento e l'elenco dei file scelti.

       I quattro preventDefault() sui trascinamenti non sono decorativi: senza
       di essi il browser aprirebbe il file trascinato in una scheda nuova,
       buttando via la pagina con tutto quello che c'era scritto dentro.
       -------------------------------------------------------------------- */

    function pesoLeggibile(byte) {
        if (byte < 1024) {
            return byte + " byte";
        }
        if (byte < 1024 * 1024) {
            return Math.round(byte / 1024) + " kB";
        }
        return (byte / (1024 * 1024)).toFixed(1) + " MB";
    }

    function mostraFileScelti(area) {
        var campo = area.querySelector("input[type=file]");
        var elenco = area.querySelector("[data-area-file-elenco]");
        if (!campo || !elenco) {
            return;
        }

        elenco.innerHTML = "";

        if (!campo.files || campo.files.length === 0) {
            elenco.hidden = true;
            return;
        }

        for (var i = 0; i < campo.files.length; i++) {
            var file = campo.files[i];
            var riga = document.createElement("li");

            var nome = document.createElement("span");
            /* textContent e non innerHTML: il nome del file lo sceglie chi
               carica, e non deve poter diventare codice dentro la pagina. */
            nome.textContent = file.name;

            var peso = document.createElement("span");
            peso.className = "peso";
            peso.textContent = pesoLeggibile(file.size);

            riga.appendChild(nome);
            riga.appendChild(peso);
            elenco.appendChild(riga);
        }

        elenco.hidden = false;
    }

    var aree = document.querySelectorAll("[data-area-file]");
    for (var a = 0; a < aree.length; a++) {
        (function (area) {
            var campo = area.querySelector("input[type=file]");
            if (!campo) {
                return;
            }

            ["dragenter", "dragover", "dragleave", "drop"].forEach(function (evento) {
                area.addEventListener(evento, function (e) {
                    e.preventDefault();
                    e.stopPropagation();
                });
            });

            ["dragenter", "dragover"].forEach(function (evento) {
                area.addEventListener(evento, function () {
                    area.classList.add("area-file--pronta");
                });
            });

            ["dragleave", "drop"].forEach(function (evento) {
                area.addEventListener(evento, function () {
                    area.classList.remove("area-file--pronta");
                });
            });

            area.addEventListener("drop", function (e) {
                if (e.dataTransfer && e.dataTransfer.files.length) {
                    /* I file trascinati si mettono dentro il campo vero: cosi'
                       li invia il modulo normale, e non serve nessuna chiamata
                       scritta a mano. */
                    campo.files = e.dataTransfer.files;
                    mostraFileScelti(area);
                }
            });

            campo.addEventListener("change", function () {
                mostraFileScelti(area);
            });
        })(aree[a]);
    }

    /* ----------------------------------------------------------------------
       4. Barra di avanzamento del caricamento

       IL PROBLEMA. Un modulo che manda un file da 300 MB, inviato nel modo
       normale, non da' nessun segno di vita finche' non ha finito: chi ha
       premuto non sa se sta succedendo qualcosa, e dopo venti secondi preme
       di nuovo.

       LA SOLUZIONE. Si intercetta l'invio e si manda lo stesso modulo con una
       XMLHttpRequest, che a differenza del modulo normale avvisa a ogni
       blocco di byte partito. Il server non se ne accorge: gli arriva lo
       stesso multipart/form-data, con lo stesso gettone CSRF dentro.

       SENZA JAVASCRIPT NON CAMBIA NIENTE. Questo pezzo si aggancia solo ai
       moduli che dichiarano data-carica-con-avanzamento; se lo script non
       arriva, quei moduli si inviano da soli come sempre e la barra resta
       nascosta. Caricare un documento non dipende da uno script (D-036).

       PERCHE' XMLHttpRequest E NON fetch(). fetch() non sa dire quanti byte
       ha spedito: l'avanzamento in salita non fa parte della sua interfaccia.
       E' l'unico posto di Aurora in cui la libreria vecchia fa una cosa che
       la nuova non sa fare.
       -------------------------------------------------------------------- */

    function percentuale(evento) {
        if (!evento.lengthComputable || !evento.total) {
            return null;
        }
        return Math.round((evento.loaded / evento.total) * 100);
    }

    function aggiornaBarra(barra, valore, testo) {
        var traccia = barra.querySelector("[role=progressbar]");
        var riempimento = barra.querySelector("[data-barra-riempimento]");
        var scritta = barra.querySelector("[data-barra-testo]");

        if (valore !== null && riempimento) {
            riempimento.style.width = valore + "%";
        }
        if (valore !== null && traccia) {
            traccia.setAttribute("aria-valuenow", String(valore));
        }
        if (scritta) {
            scritta.textContent = testo;
        }
    }

    function pesoTotale(modulo) {
        var totale = 0;
        var campi = modulo.querySelectorAll("input[type=file]");
        for (var i = 0; i < campi.length; i++) {
            var scelti = campi[i].files || [];
            for (var j = 0; j < scelti.length; j++) {
                totale += scelti[j].size;
            }
        }
        return totale;
    }

    function mostraRisposta(testo) {
        /* La risposta e' una pagina intera: il modulo rimostrato con il suo
           messaggio di errore in italiano. La si scrive al posto di quella di
           adesso. Non e' elegante, ma e' l'unico modo di far leggere il
           messaggio del server senza riscrivere in JavaScript la pagina che
           il server sa gia' comporre. Succede solo quando il caricamento
           viene rifiutato. */
        document.open();
        document.write(testo);
        document.close();
    }

    var moduli = document.querySelectorAll("[data-carica-con-avanzamento]");
    for (var m = 0; m < moduli.length; m++) {
        (function (modulo) {
            var barra = modulo.querySelector("[data-barra-caricamento]");
            if (!barra || typeof window.FormData !== "function") {
                return;
            }

            modulo.addEventListener("submit", function (evento) {
                if (pesoTotale(modulo) === 0) {
                    /* Nessun file scelto: si lascia fare al modulo normale,
                       cosi' e' il server a rispondere "scegli un file" con la
                       sua frase italiana, in un posto solo. */
                    return;
                }

                evento.preventDefault();

                var invio = modulo.querySelector("button[type=submit]");
                if (invio) {
                    invio.disabled = true;
                }

                barra.hidden = false;
                barra.classList.remove("barra-caricamento--conclusa");
                barra.classList.remove("barra-caricamento--fallita");
                aggiornaBarra(barra, 0, "Caricamento in corso...");

                var richiesta = new XMLHttpRequest();
                richiesta.open(modulo.method || "post", modulo.action, true);

                richiesta.upload.addEventListener("progress", function (e) {
                    var valore = percentuale(e);
                    if (valore === null) {
                        aggiornaBarra(barra, null, "Caricamento in corso...");
                        return;
                    }
                    aggiornaBarra(
                        barra,
                        valore,
                        valore + "% - " + pesoLeggibile(e.loaded) +
                            " di " + pesoLeggibile(e.total)
                    );
                });

                richiesta.upload.addEventListener("load", function () {
                    /* I byte sono partiti tutti: da qui in avanti si aspetta
                       che il server finisca di scriverli. Dirlo evita la
                       barra ferma al 100% che sembra bloccata. */
                    aggiornaBarra(barra, 100, "Il server sta salvando i file...");
                });

                richiesta.addEventListener("load", function () {
                    if (richiesta.status >= 200 && richiesta.status < 400) {
                        barra.classList.add("barra-caricamento--conclusa");
                        aggiornaBarra(barra, 100, "Caricamento completato.");
                        /* La richiesta ha gia' seguito il rimando del server:
                           responseURL e' la pagina di arrivo. */
                        window.location.href =
                            richiesta.responseURL || modulo.action;
                        return;
                    }
                    barra.classList.add("barra-caricamento--fallita");
                    aggiornaBarra(barra, 100, "Il caricamento non e' riuscito.");
                    mostraRisposta(richiesta.responseText);
                });

                richiesta.addEventListener("error", function () {
                    barra.classList.add("barra-caricamento--fallita");
                    aggiornaBarra(
                        barra,
                        100,
                        "Collegamento interrotto: il file non e' stato caricato."
                    );
                    if (invio) {
                        invio.disabled = false;
                    }
                });

                richiesta.send(new FormData(modulo));
            });
        })(moduli[m]);
    }
})();
