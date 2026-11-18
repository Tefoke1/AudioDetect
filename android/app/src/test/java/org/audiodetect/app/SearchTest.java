package org.audiodetect.app;
import org.junit.Test;
import static org.junit.Assert.*;
public class SearchTest {
 @Test public void inflectedAddress(){assertTrue(Search.matches("на Тополиной дом пять", "Тополиная 5",0,false));}
 @Test public void wrongHouse(){assertFalse(Search.matches("Тополиная двадцать пять", "Тополиная 5",0,true));assertFalse(Search.matches("Тополиная 5а", "Тополиная 5",0,true));assertFalse(Search.matches("Тополиная 5-а", "Тополиная 5",0,true));}
 @Test public void unrelatedNumeric(){assertFalse(Search.equal("15","5",true));}
 @Test public void allWordsSameRecording(){assertTrue(Search.matches("договор обсудили. После перерыва согласовали оплату", "договор оплата",1,false));assertFalse(Search.matches("договор согласовали", "договор оплата",1,false));}
 @Test public void anyWord(){assertTrue(Search.matches("проект готов", "проект оплата",2,false));}
 @Test public void emptyQuery(){assertFalse(Search.matches("a", "",1,true));}
 @Test public void englishInflection(){assertTrue(Search.matches("contracts and payments", "contract payment",1,false));}
 @Test public void separateAlternatives(){assertTrue(Search.matches("revised deadline", "budget approval; revised deadline",0,false));}
 @Test public void escapeSpreadsheet(){assertEquals("\"'=SUM(A1)\"",Search.csv("=SUM(A1)"));}
 @Test public void fuzzyAndExact(){assertTrue(Search.equal("тополиная","таполиная",true));assertFalse(Search.equal("тополиная","таполиная",false));}
}