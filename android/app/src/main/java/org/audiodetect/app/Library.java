package org.audiodetect.app;

import android.content.*;
import android.database.*;
import android.database.sqlite.*;
import org.json.*;
import java.util.*;

final class Library extends SQLiteOpenHelper {
    Library(Context c){super(c,"library.sqlite",null,1);setWriteAheadLoggingEnabled(true);}
    public void onCreate(SQLiteDatabase db){db.execSQL("CREATE TABLE recordings(uri TEXT PRIMARY KEY,name TEXT,size INTEGER,modified INTEGER,selected INTEGER DEFAULT 1,language TEXT DEFAULT '',transcript TEXT DEFAULT '',error TEXT DEFAULT '')");}
    public void onUpgrade(SQLiteDatabase db,int old,int version){}
    static final class Entry {
        String uri,name,language,text,error;long size,modified;boolean selected;
        JSONArray segments(){try{return new JSONArray(text);}catch(Exception e){return new JSONArray();}}
        String words(){StringBuilder s=new StringBuilder();JSONArray parts=segments();for(int i=0;i<parts.length();i++)s.append(parts.optJSONObject(i).optString("text")).append(' ');return s.toString();}
    }
    List<Entry> entries(){List<Entry> list=new ArrayList<>();try(Cursor c=getReadableDatabase().rawQuery("SELECT * FROM recordings ORDER BY name COLLATE NOCASE",null)){while(c.moveToNext()){Entry e=new Entry();e.uri=c.getString(0);e.name=c.getString(1);e.size=c.getLong(2);e.modified=c.getLong(3);e.selected=c.getInt(4)!=0;e.language=c.getString(5);e.text=c.getString(6);e.error=c.getString(7);list.add(e);}}return list;}
    void add(String uri,String name,long size,long modified){SQLiteDatabase db=getWritableDatabase();ContentValues v=new ContentValues();v.put("uri",uri);v.put("name",name);v.put("size",size);v.put("modified",modified);db.beginTransaction();try{long n=db.insertWithOnConflict("recordings",null,v,SQLiteDatabase.CONFLICT_IGNORE);if(n<0){try(Cursor c=db.rawQuery("SELECT size,modified FROM recordings WHERE uri=?",new String[]{uri})){if(c.moveToFirst()&&(c.getLong(0)!=size||c.getLong(1)!=modified)){v.put("transcript","");v.put("language","");v.put("error","");}}db.update("recordings",v,"uri=?",new String[]{uri});}db.setTransactionSuccessful();}finally{db.endTransaction();}}
    void select(String uri,boolean selected){ContentValues v=new ContentValues();v.put("selected",selected?1:0);getWritableDatabase().update("recordings",v,"uri=?",new String[]{uri});}
    void selectMany(List<Entry> entries,boolean selected){SQLiteDatabase db=getWritableDatabase();db.beginTransaction();try{for(Entry e:entries)select(e.uri,selected);db.setTransactionSuccessful();}finally{db.endTransaction();}}
    void save(String uri,String language,JSONArray text,String error){ContentValues v=new ContentValues();v.put("language",language);v.put("transcript",text.toString());v.put("error",error);getWritableDatabase().update("recordings",v,"uri=?",new String[]{uri});}
}
