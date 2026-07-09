# Die Verwandlung — beginner chunking, sample review

Level: beginner (min 2 / target 3 / max 5). 892 sentences, 5931 chunks, 0 reconstruction failures.

Chunks are separated by ` | `.


## The famous opening

- Als Gregor Samsa eines Morgens | aus unruhigen Träumen erwachte, | fand er sich | in seinem Bett | zu einem ungeheueren Ungeziefer verwandelt.
- Er lag | auf seinem panzerartig harten Rücken | und sah, | wenn er den Kopf | ein wenig hob, | seinen gewölbten, braunen, | von bogenförmigen Versteifungen geteilten Bauch, | auf dessen Höhe sich | die Bettdecke, | zum gänzlichen Niedergleiten bereit, | kaum noch erhalten konnte.
- Seine vielen, | im Vergleich | zu seinem sonstigen Umfang | kläglich dünnen Beine flimmerten | ihm hilflos | vor den Augen.

## The longest sentences (worst case for any chunker)

- (110 words, 34 chunks) Und wenn nun | auch Gregor | durch seine Wunde | an Beweglichkeit wahrscheinlich | für immer verloren hatte | und vorläufig | zur Durchquerung seines Zimmers | wie ein alter Invalide | lange, lange Minuten brauchte — | an das Kriechen | in der Höhe war | nicht zu denken —, | so bekam er | für diese Verschlimmerung seines Zustandes | einen | seiner Meinung nach | vollständig genügenden Ersatz | dadurch, | daß immer gegen Abend | die Wohnzimmertür, | die er schon | ein bis zwei | Stunden vorher scharf | zu beobachten pflegte, | geöffnet wurde, so | daß er, | im Dunkel seines Zimmers liegend, | vom Wohnzimmer aus unsichtbar, | die ganze Familie | beim beleuchteten Tische sehen | und ihre Reden, | gewissermaßen mit allgemeiner Erlaubnis, | also ganz anders als früher, | anhören durfte.
- (101 words, 32 chunks) Nur mit dem letzten Blick | sah | er noch, | wie die Tür | seines Zimmers aufgerissen wurde, | und vor der schreienden Schwester | die Mutter hervoreilte, | im Hemd, | denn die Schwester hatte | sie entkleidet, | um ihr | in der Ohnmacht Atemfreiheit | zu verschaffen, | wie dann | die Mutter | auf den Vater zulief | und ihr auf dem Weg | die aufgebundenen Röcke | einer nach dem anderen | zu Boden glitten, | und wie sie stolpernd | über die Röcke | auf den Vater eindrang | und ihn umarmend, | in gänzlicher Vereinigung | mit ihm — | nun versagte aber | Gregors Sehkraft schon — | die Hände | an des Vaters Hinterkopf | um Schonung | von Gregors Leben bat.
- (95 words, 29 chunks) Aber das hohe freie Zimmer, | in dem er gezwungen war, | flach auf dem Boden | zu liegen, | ängstigte ihn, | ohne daß er die Ursache | herausfinden konnte, | denn es war ja | sein seit fünf Jahren | von ihm bewohntes Zimmer — | und mit einer | halb unbewußten Wendung | und nicht ohne | eine leichte Scham | eilte | er unter das Kanapee, | wo er sich, trotzdem | sein Rücken | ein wenig gedrückt wurde | und trotzdem | er den Kopf | nicht mehr erheben konnte, | gleich sehr behaglich fühlte | und nur bedauerte, | daß sein Körper | zu breit war, | um vollständig | unter dem Kanapee untergebracht | zu werden.

## Dialogue with »guillemets«

- »Ach Gott,« | dachte er, | »was für einen anstrengenden Beruf | habe | ich gewählt!
- »Himmlischer Vater!« dachte er, | Es war | halb sieben Uhr, | und die Zeiger gingen | ruhig vorwärts, | es war sogar halb vorüber, | es näherte sich schon dreiviertel.
- Gregor hatte | ausführlich antworten | und alles erklären wollen, | beschränkte sich aber | bei diesen Umständen darauf, | zu sagen: | »Ja, ja, | danke, Mutter, | ich stehe schon auf.
- Nach beiden Seiten hin antwortete | Gregor: »Bin schon fertig,« | und bemühte sich, | durch die sorgfältigste Aussprache | und durch Einschaltung | von langen Pausen | zwischen den einzelnen Worten | seiner Stimme | alles Auffallende | zu nehmen.
- Der Vater kehrte | auch zu seinem Frühstück zurück, | die Schwester aber flüsterte: | »Gregor, mach auf, | ich beschwöre dich.

## Verb-final clauses (German bracket)

- Es stellte eine Dame dar, | die, mit einem Pelzhut | und einer Pelzboa versehen, | aufrecht dasaß | und einen schweren Pelzmuff, | in dem ihr ganzer Unterarm | verschwunden war, | dem Beschauer entgegenhob.
- « Er fühlte | ein leichtes Jucken oben | auf dem Bauch; | schob sich | auf dem Rücken langsam näher | zum Bettpfosten, | um den Kopf besser heben | zu können; | fand die juckende Stelle, | die mit lauter | kleinen weißen Pünktchen | besetzt war, | die er nicht | zu beurteilen verstand;
- Gregor erschrak, | als er seine antwortende Stimme | hörte, | die wohl unverkennbar | seine frühere war, | in die sich aber, | wie von unten her, | ein nicht zu unterdrückendes, | schmerzliches Piepsen mischte, | das die Worte förmlich | nur im ersten Augenblick | in ihrer Deutlichkeit beließ, | um sie | im Nachklang derart zu zerstören, | daß man nicht wußte, | ob man recht gehört hatte.
- Aber durch das kleine Gespräch | waren | die anderen Familienmitglieder | darauf aufmerksam geworden, | daß Gregor | wider Erwarten noch | zu Hause war, | und schon klopfte | an der einen Seitentür | der Vater, | schwach, aber mit der Faust.

## Residual rough spots (quantified over all 5931 chunks)

| pattern | count | share | example |
|---|---|---|---|
| chunk ends in stranded prep/article/subordinator | 34 | 0.57% | `wo man bei \| der kleinsten Versäumnis` |
| cut violates a fuse-right word | 90 | 1.51% | mostly benign adjective-list commas: `einen noch nie gefühlten, \| leichten, dumpfen Schmerz` |
| mid-sentence 1-word chunk | ~59 | 1.0% | `... auf die rechte Seite \| warf, \| ...` (stranded verb-final verb; the floor=1 fallback tier trade-off) |
| punctuation-only chunk | 0 | — | fixed: absorbed into neighbours |
| chunk over max words | 16 | 0.3% | unbreakable fusion runs |

The stranded verb-final verb (`warf,`, `eilte`) arguably *helps* a learner — the verb
arrives as its own beat, mirroring how German holds it to the end. The stranded
prepositions/articles (0.57%) are the only truly confusing pattern, and they occur
only where a fusion chain longer than max_words leaves no legal cut.
