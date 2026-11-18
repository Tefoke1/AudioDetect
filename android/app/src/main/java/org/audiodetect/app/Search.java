package org.audiodetect.app;

import java.text.Normalizer;
import java.util.*;
import java.util.regex.*;

/** Query matching only: word co-occurrence is not proof of a shared topic. */
public final class Search {
    private static final Map<String,String> NUMBERS = new HashMap<>();
    static {
        String[][] rows = {{"zero","ноль","0"},{"one","один","1"},{"two","два","2"},{"three","три","3"},{"four","четыре","4"},{"five","пять","5"},{"six","шесть","6"},{"seven","семь","7"},{"eight","восемь","8"},{"nine","девять","9"},{"ten","десять","10"},{"eleven","одиннадцать","11"},{"twelve","двенадцать","12"},{"thirteen","тринадцать","13"},{"fourteen","четырнадцать","14"},{"fifteen","пятнадцать","15"},{"sixteen","шестнадцать","16"},{"seventeen","семнадцать","17"},{"eighteen","восемнадцать","18"},{"nineteen","девятнадцать","19"},{"twenty","двадцать","20"},{"thirty","тридцать","30"},{"forty","сорок","40"},{"fifty","пятьдесят","50"},{"sixty","шестьдесят","60"},{"seventy","семьдесят","70"},{"eighty","восемьдесят","80"},{"ninety","девяносто","90"}};
        for(String[] r:rows){NUMBERS.put(r[0],r[2]);NUMBERS.put(r[1],r[2]);}
    }
    public static List<String> tokens(String text) {
        Matcher m=Pattern.compile("[\\p{L}]+|\\d+(?:[/-](?:\\d+[\\p{L}]?|[\\p{L}]))?[\\p{L}]?").matcher(Normalizer.normalize(text.toLowerCase(Locale.ROOT).replace('ё','е'),Normalizer.Form.NFKC));
        List<String> out=new ArrayList<>();
        while(m.find()) {String token=NUMBERS.getOrDefault(m.group(),m.group());
            if(!out.isEmpty() && token.matches("[1-9]") && out.get(out.size()-1).matches("[2-9]0")) {
                out.set(out.size()-1,Integer.toString(Integer.parseInt(out.get(out.size()-1))+Integer.parseInt(token)));
            } else out.add(token);
        }
        return out;
    }
    private static String stem(String s) {
        if(s.matches(".*\\d.*"))return s;
        String r=s.replaceFirst("(иями|ями|ами|ого|ему|ому|ыми|ими|ая|ой|ую|ые|ий|ый|ое|ей|ия|ию|ов|ам|ах|ом|ем|ях|ы|и|а|я|е|у|ю)$","");
        if(s.matches("[a-z]+") && s.length()>5)return s.replaceFirst("(ing|ed|es|s)$","");
        return r.length()>=4?r:s;
    }
    public static boolean equal(String a,String b,boolean fuzzy) {
        if(a.equals(b))return true;
        if(a.matches(".*\\d.*")||b.matches(".*\\d.*"))return false;
        a=stem(a);b=stem(b);if(a.equals(b))return true;
        if(!fuzzy||Math.min(a.length(),b.length())<5)return false;
        int[] prev=new int[b.length()+1];for(int j=0;j<prev.length;j++)prev[j]=j;
        for(int i=1;i<=a.length();i++){int[] row=new int[b.length()+1];row[0]=i;for(int j=1;j<=b.length();j++)row[j]=Math.min(Math.min(row[j-1]+1,prev[j]+1),prev[j-1]+(a.charAt(i-1)==b.charAt(j-1)?0:1));prev=row;}
        return prev[b.length()]<=Math.max(a.length(),b.length())/5;
    }
    public static boolean matches(String text,String query,int mode,boolean fuzzy) {
        List<String> hay=tokens(text),need=tokens(query);if(need.isEmpty())return false;
        if(mode>0) {
            boolean all=true,any=false;
            for(String term:need){boolean found=false;for(String word:hay)if(equal(term,word,fuzzy)){found=true;break;}all &= found;any |= found;}
            return mode==1?all:any;
        }
        for(String alternative:query.split(";")) {
            List<String> phrase=tokens(alternative);
            phrase.removeIf(w->Arrays.asList("на","по","улица","улице","дом","д","ул","the","on","at","house","street").contains(w));
            if(phrase.isEmpty())continue;
            if(ordered(hay,phrase,fuzzy))return true;
            if(phrase.size()==2 && phrase.get(1).matches("\\d+")) {
                Collections.reverse(phrase);if(ordered(hay,phrase,fuzzy))return true;
            }
        }
        return false;
    }
    private static boolean ordered(List<String> hay,List<String> need,boolean fuzzy) {
        for(int start=0;start<hay.size();start++) {
            if(!equal(hay.get(start),need.get(0),fuzzy))continue;
            int pos=start;boolean found=true;
            for(int n=1;n<need.size();n++) {int next=-1;for(int i=pos+1;i<Math.min(hay.size(),pos+5);i++) {if(equal(hay.get(i),need.get(n),fuzzy)){next=i;break;}if(hay.get(i).matches(".*\\d.*"))break;}if(next<0){found=false;break;}pos=next;}
            if(found)return true;
        }
        return false;
    }
    public static String time(double seconds){int s=(int)Math.max(0,seconds);return s>=3600?String.format(Locale.ROOT,"%d:%02d:%02d",s/3600,s/60%60,s%60):String.format(Locale.ROOT,"%02d:%02d",s/60,s%60);}
    public static String csv(String value){if(value.matches("^[=+@\\-\\t\\r].*"))value="'"+value;return "\""+value.replace("\"","\"\"")+"\"";}
}
