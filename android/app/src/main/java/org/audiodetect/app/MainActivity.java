package org.audiodetect.app;

import android.app.*;
import android.content.*;
import android.database.Cursor;
import android.graphics.Color;
import android.media.MediaPlayer;
import android.net.Uri;
import android.os.*;
import android.provider.*;
import android.text.*;
import android.view.*;
import android.widget.*;
import org.json.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.text.*;
import java.util.*;

/** Guided offline search: recordings, query, then evidence with playback. */
public final class MainActivity extends Activity {
    private static final int FILES=10,TREE=11,EXPORT=12;
    AlertDialog languageDialog;
    String language="ru",activeJob="";
    Library library;
    LinearLayout root,filesPage,queryPage,searchPage,filterPanel;
    ListView fileList,resultList;
    EditText nameFilter,dateFrom,dateTo,sizeMin,sizeMax,query;
    Spinner mode,speech;
    CheckBox fuzzy,economical;
    TextView count,status,metrics,activeFiles,resultsCount,emptyResults,modeHint,selectionSummary;
    Button run,stop,back,filters,resume,exportButton;
    Button[] steps=new Button[3];
    ProgressBar progressBar;
    List<Library.Entry> visible=new ArrayList<>();
    List<Result> matches=new ArrayList<>();
    boolean running=false,scanning=false,filtersOpen=false;
    int anchor=-1,stage=0;
    MediaPlayer player;
    Handler handler=new Handler(Looper.getMainLooper());
    Handler progressHandler=new Handler(Looper.getMainLooper());
    String csv="";
    FileAdapter fileAdapter;
    ResultAdapter resultAdapter;
    static class Result {
        Library.Entry file;double start,end;String excerpt,summary;
        Result(Library.Entry f,double a,double b,String text){
            file=f;start=a;end=b;excerpt=text;summary=text.length()>150?text.substring(0,150)+"…":text;
        }
    }
    String t(String ru,String en){return language.equals("ru")?ru:en;}
    int dp(int n){return Ui.dp(this,n);}
    TextView text(String value,int size){
        TextView v=new TextView(this);v.setText(value);Ui.text(v,size,false);
        v.setPadding(0,dp(5),0,dp(5));return v;
    }
    TextView muted(String value){TextView v=text(value,13);v.setTextColor(Ui.MUTED);return v;}
    TextView heading(String value){TextView v=text(value,25);v.setTypeface(null,1);return v;}
    Button button(String value,Runnable action){
        Button b=new Button(this);b.setText(value);Ui.button(b,false);b.setOnClickListener(v->action.run());return b;
    }
    LinearLayout column(){LinearLayout c=new LinearLayout(this);c.setOrientation(LinearLayout.VERTICAL);return c;}
    LinearLayout row(){LinearLayout c=new LinearLayout(this);c.setOrientation(LinearLayout.HORIZONTAL);c.setGravity(Gravity.CENTER_VERTICAL);return c;}
    EditText edit(String hint){
        EditText e=new EditText(this);e.setSingleLine(true);e.setHint(hint);e.setContentDescription(hint);Ui.input(e);return e;
    }
    void weighted(LinearLayout row,View view){
        LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(0,-2,1);p.setMargins(dp(3),dp(3),dp(3),dp(3));row.addView(view,p);
    }
    void add(LinearLayout parent,View child){LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,-2);p.setMargins(0,dp(5),0,dp(5));parent.addView(child,p);}
    void watch(EditText e,Runnable callback){
        e.addTextChangedListener(new TextWatcher(){
            public void beforeTextChanged(CharSequence s,int st,int c,int a){}
            public void onTextChanged(CharSequence s,int st,int before,int count){callback.run();}
            public void afterTextChanged(Editable e){}
        });
    }
    ScrollView scroll(LinearLayout child){ScrollView s=new ScrollView(this);s.setFillViewport(true);s.addView(child);return s;}
    final BroadcastReceiver events=new BroadcastReceiver(){public void onReceive(Context c,Intent i){
        if(status==null)return;
        try{applyProgress(new JSONObject(i.getStringExtra("state")));}catch(Exception ignored){}
    }};
    final Runnable pollProgress=new Runnable(){public void run(){
        if(root!=null && running)readProgress();
        progressHandler.postDelayed(this,1000);
    }};
    @Override public void onCreate(Bundle saved){
        super.onCreate(saved);activeJob=getPreferences(0).getString("jobId","");library=new Library(this);language=getPreferences(0).getString("language","ru");
        if(Build.VERSION.SDK_INT>=33)registerReceiver(events,new IntentFilter(RecognitionService.EVENT),Context.RECEIVER_NOT_EXPORTED);
        else registerReceiver(events,new IntentFilter(RecognitionService.EVENT));
        // List items are kept for accessible selection and the integration runner.
        languageDialog=new AlertDialog.Builder(this).setTitle("AudioDetect · Language / Язык")
            .setItems(new String[]{"Русский","English"},(d,which)->chooseLanguage(which==0?"ru":"en"))
            .setCancelable(false).create();
        languageDialog.show();
    }
    void chooseLanguage(String value){
        language=value;getPreferences(0).edit().putString("language",language).apply();build();
        progressHandler.removeCallbacks(pollProgress);progressHandler.post(pollProgress);
    }
    void build(){
        root=column();root.setBackground(Ui.background());root.setPadding(dp(16),dp(10),dp(16),dp(10));
        setContentView(root);getWindow().getDecorView().setSystemUiVisibility(0);
        getWindow().setStatusBarColor(Ui.BG);getWindow().setNavigationBarColor(Ui.BG);
        root.setOnApplyWindowInsetsListener((view,insets)->{
            view.setPadding(dp(16),dp(10)+insets.getSystemWindowInsetTop(),dp(16),dp(10)+insets.getSystemWindowInsetBottom());return insets;
        });root.requestApplyInsets();
        LinearLayout brand=row();
        TextView mark=text("▥",30);mark.setTextColor(Ui.CORAL);mark.setPadding(0,0,dp(10),0);brand.addView(mark);
        TextView title=text("AudioDetect",24);title.setTypeface(null,1);brand.addView(title,new LinearLayout.LayoutParams(0,-2,1));
        TextView privacy=muted(t("На устройстве","On device"));brand.addView(privacy);root.addView(brand);
        LinearLayout stepper=row();String[] names={t("1  Записи","1  Recordings"),t("2  Запрос","2  Query"),t("3  Результаты","3  Results")};
        for(int i=0;i<3;i++){final int index=i;steps[i]=button(names[i],()->showStage(index));steps[i].setTextSize(12);steps[i].setPadding(dp(3),dp(8),dp(3),dp(8));weighted(stepper,steps[i]);}
        add(root,stepper);
        android.widget.FrameLayout pages=new android.widget.FrameLayout(this);root.addView(pages,new LinearLayout.LayoutParams(-1,0,1));
        filesPage=column();pages.addView(filesPage,new android.widget.FrameLayout.LayoutParams(-1,-1));
        queryPage=column();ScrollView queryScroll=scroll(queryPage);queryScroll.setTag("query-scroll");pages.addView(queryScroll,new android.widget.FrameLayout.LayoutParams(-1,-1));
        searchPage=column();pages.addView(searchPage,new android.widget.FrameLayout.LayoutParams(-1,-1));
        buildFiles();buildQuery();buildResults();
        LinearLayout footer=row();
        back=button(t("Назад","Back"),()->showStage(Math.max(0,stage-1)));
        footer.addView(back,new LinearLayout.LayoutParams(dp(92),-2));
        run=button("",()->{if(stage==0)showStage(1);else if(stage==1)start();else export();});
        Ui.button(run,true);weighted(footer,run);add(root,footer);
        ActivityManager am=(ActivityManager)getSystemService(ACTIVITY_SERVICE);
        running=false;
        for(ActivityManager.RunningServiceInfo service:am.getRunningServices(100))
            if(service.service.getClassName().equals(RecognitionService.class.getName()))running=true;
        refreshFiles();showStage(running?2:0);readProgress();
    }
    void buildFiles(){
        add(filesPage,heading(t("Выберите разговоры","Choose conversations")));
        add(filesPage,muted(t("Добавьте папку или несколько записей. Исходные файлы останутся на месте.",
                "Add a folder or individual recordings. Source files stay where they are.")));
        LinearLayout sources=row();
        Button folder=button(t("Добавить папку","Add a folder"),()->{
            Intent i=new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
            i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION|Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);startActivityForResult(i,TREE);
        });
        Ui.button(folder,true);weighted(sources,folder);
        weighted(sources,button(t("Выбрать файлы","Choose files"),()->{
            Intent i=new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("audio/*").addCategory(Intent.CATEGORY_OPENABLE).putExtra(Intent.EXTRA_ALLOW_MULTIPLE,true);
            i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION|Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);startActivityForResult(i,FILES);
        }));add(filesPage,sources);
        filters=button(t("Фильтры по имени, дате и размеру","Filter by name, date and size"),this::showFilters);add(filesPage,filters);
        filterPanel=column();Ui.panel(filterPanel);
        nameFilter=edit(t("Название содержит…","Name contains…"));add(filterPanel,nameFilter);
        add(filterPanel,muted(t("Дата изменения файла","File modification date")));
        LinearLayout dates=row();dateFrom=edit(t("Дата с","From date"));dateTo=edit(t("Дата по","Through date"));
        for(EditText date:new EditText[]{dateFrom,dateTo}){
            date.setFocusable(false);date.setTextSize(14);date.setOnClickListener(v->chooseDate(date));weighted(dates,date);
        }
        add(filterPanel,dates);
        LinearLayout sizes=row();sizeMin=edit(t("От, МиБ","Min MiB"));sizeMax=edit(t("До, МиБ","Max MiB"));
        sizeMin.setInputType(8194);sizeMax.setInputType(8194);sizeMin.setTextSize(14);sizeMax.setTextSize(14);weighted(sizes,sizeMin);weighted(sizes,sizeMax);add(filterPanel,sizes);
        add(filterPanel,button(t("Сбросить фильтры","Clear filters"),()->{
            nameFilter.setText("");dateFrom.setText("");dateTo.setText("");sizeMin.setText("");sizeMax.setText("");
        }));
        LinearLayout selection=row();weighted(selection,button(t("Выбрать всё","Select all"),()->bulk(true)));weighted(selection,button(t("Снять выбор","Clear selection"),()->bulk(false)));add(filesPage,selection);
        count=muted("");add(filesPage,count);
        fileList=new ListView(this);fileList.setDivider(null);fileList.setCacheColorHint(Color.TRANSPARENT);
        fileAdapter=new FileAdapter();fileList.setAdapter(fileAdapter);
        filesPage.addView(fileList,new LinearLayout.LayoutParams(-1,0,1));
        TextView empty=muted(t("Здесь появятся ваши записи.\nНачните с кнопки «Добавить папку».","Your recordings will appear here.\nStart with “Add a folder”."));
        empty.setGravity(Gravity.CENTER);filesPage.addView(empty);fileList.setEmptyView(empty);
        add(filesPage,muted(t("В работу попадут отмеченные записи по текущему фильтру. Долгое нажатие выделяет диапазон.",
                "Only checked recordings in this filter are processed. Long-press to select a range.")));
        for(EditText e:new EditText[]{nameFilter,dateFrom,dateTo,sizeMin,sizeMax})watch(e,this::refreshFiles);
    }
    void showFilters(){
        if(filterPanel.getParent()!=null)((ViewGroup)filterPanel.getParent()).removeView(filterPanel);
        ScrollView content=scroll(filterPanel);
        AlertDialog dialog=new AlertDialog.Builder(this).setTitle(t("Отбор записей","Filter recordings"))
            .setView(content).setPositiveButton(t("Показать записи","Show recordings"),(d,w)->refreshFiles()).create();
        dialog.setOnDismissListener(d->{content.removeView(filterPanel);refreshFiles();});dialog.show();
    }
    void chooseDate(EditText target){
        Calendar c=Calendar.getInstance();
        DatePickerDialog dialog=new DatePickerDialog(this,(view,y,m,d)->target.setText(String.format(Locale.ROOT,"%04d-%02d-%02d",y,m+1,d)),
                c.get(Calendar.YEAR),c.get(Calendar.MONTH),c.get(Calendar.DAY_OF_MONTH));
        dialog.setButton(DialogInterface.BUTTON_NEUTRAL,t("Без даты","Any date"),(d,w)->target.setText(""));dialog.show();
    }
    void buildQuery(){
        add(queryPage,heading(t("Что нужно найти?","What do you need to find?")));
        add(queryPage,muted(t("Введите слова из нужного разговора. Например, тему, адрес или название проекта.",
                "Enter words from the conversation: a topic, address or project name.")));
        selectionSummary=text("",14);selectionSummary.setTextColor(Ui.CORAL);add(queryPage,selectionSummary);
        add(queryPage,text(t("Слова или фраза","Words or phrase"),14));
        query=edit(t("Например: договор сроки оплата","For example: contract deadline payment"));
        query.setText(getPreferences(0).getString("query",""));add(queryPage,query);
        add(queryPage,text(t("Как искать","How to match"),14));
        mode=new Spinner(this);Ui.spinner(mode,new String[]{t("Фраза: слова рядом","Phrase: words together"),t("Все слова в разговоре","All words in the conversation"),t("Хотя бы одно слово","Any of these words")});
        mode.setSelection(getPreferences(0).getInt("mode",1));add(queryPage,mode);
        modeHint=muted("");add(queryPage,modeHint);
        mode.setOnItemSelectedListener(new android.widget.AdapterView.OnItemSelectedListener(){
            public void onNothingSelected(android.widget.AdapterView<?> p){}
            public void onItemSelected(android.widget.AdapterView<?> p,View v,int position,long id){updateModeHint();}
        });
        fuzzy=new CheckBox(this);Ui.check(fuzzy);fuzzy.setText(t("Учитывать похожие написания","Allow similar spellings"));fuzzy.setChecked(true);add(queryPage,fuzzy);
        LinearLayout example=column();Ui.panel(example);
        add(example,text(t("Попробуйте на примере","Try an example"),16));
        add(example,muted(t("«договор оплата» найдёт запись, где встретились оба слова, даже в разных репликах.",
                "“contract payment” finds a recording containing both words, even in different sentences.")));
        add(example,button(t("Вставить пример","Use example"),()->{query.setText(t("договор оплата","contract payment"));mode.setSelection(1);}));
        add(queryPage,example);
        LinearLayout settings=column();settings.setVisibility(View.GONE);
        add(queryPage,button(t("Язык речи и скорость","Speech language and speed"),()->settings.setVisibility(settings.getVisibility()==View.VISIBLE?View.GONE:View.VISIBLE)));
        add(settings,text(t("Язык, на котором говорят","Language spoken"),14));
        speech=new Spinner(this);Ui.spinner(speech,new String[]{"Русский","English"});
        speech.setSelection(getPreferences(0).getInt("speech",language.equals("en")?1:0));add(settings,speech);
        economical=new CheckBox(this);Ui.check(economical);economical.setText(t("Экономный режим: одна запись за раз","Economy mode: one recording at a time"));
        economical.setChecked(getPreferences(0).getBoolean("economical",false));add(settings,economical);
        add(settings,muted(t("Обычно проверяем до двух записей одновременно. При перегреве или экономии батареи нагрузка снижается. Точность режимов одинакова.",
                "Normally checks up to two recordings at once. Heat and battery saver reduce concurrency. Both modes use the same accuracy settings.")));
        add(queryPage,settings);
        add(queryPage,muted(t("Новые записи распознаются один раз. Следующие запросы используют готовый текст. Аудио и текст остаются на телефоне.",
                "New recordings are transcribed once. Later queries reuse saved text. Audio and text stay on this phone.")));
        watch(query,this::updateButtons);
    }
    void updateModeHint(){
        if(modeHint==null)return;
        String[] ru={"Слова должны встретиться рядом. Варианты можно разделить точкой с запятой.",
                "Каждое слово должно быть в одной записи. Порядок и расстояние между ними не важны.",
                "Достаточно любого из введённых слов. Подходит для широкого отбора."};
        String[] en={"Words must occur together. Separate alternative phrases with semicolons.",
                "Every word must occur in one recording, in any order and anywhere in it.",
                "One matching word is enough. Use this for a broader search."};
        modeHint.setText((language.equals("ru")?ru:en)[mode.getSelectedItemPosition()]);
    }
    void buildResults(){
        add(searchPage,heading(t("Найденное в разговорах","Found in conversations")));
        LinearLayout progressCard=column();Ui.panel(progressCard);
        status=text(t("Введите запрос на предыдущем шаге.","Enter a query in the previous step."),15);add(progressCard,status);
        progressBar=new ProgressBar(this,null,android.R.attr.progressBarStyleHorizontal);progressBar.setMax(1000);
        progressBar.setProgressTintList(android.content.res.ColorStateList.valueOf(Ui.CORAL));
        progressBar.setProgressBackgroundTintList(android.content.res.ColorStateList.valueOf(Ui.BG));add(progressCard,progressBar);
        metrics=muted("");add(progressCard,metrics);activeFiles=muted("");activeFiles.setMaxLines(4);add(progressCard,activeFiles);
        stop=button(t("Остановить проверку","Stop checking"),this::stop);add(progressCard,stop);
        resume=button(t("Продолжить проверку","Resume checking"),this::start);add(progressCard,resume);resume.setVisibility(View.GONE);
        add(searchPage,progressCard);
        resultsCount=text("",16);add(searchPage,resultsCount);
        resultList=new ListView(this);resultList.setDividerHeight(dp(10));resultList.setDivider(new android.graphics.drawable.ColorDrawable(Color.TRANSPARENT));
        resultAdapter=new ResultAdapter();resultList.setAdapter(resultAdapter);searchPage.addView(resultList,new LinearLayout.LayoutParams(-1,0,1));
        emptyResults=muted(t("Здесь будут фрагменты с вашими словами и кнопка прослушивания.",
                "Matching excerpts and playback controls will appear here."));
        emptyResults.setGravity(Gravity.CENTER);emptyResults.setPadding(dp(12),dp(18),dp(12),dp(18));searchPage.addView(emptyResults);resultList.setEmptyView(emptyResults);
    }
    void show(boolean queryStep){showStage(queryStep?1:0);}
    void showStage(int value){
        stage=value;filesPage.setVisibility(value==0?View.VISIBLE:View.GONE);
        ((View)queryPage.getParent()).setVisibility(value==1?View.VISIBLE:View.GONE);
        searchPage.setVisibility(value==2?View.VISIBLE:View.GONE);
        for(int i=0;i<3;i++){Ui.button(steps[i],i==value);steps[i].setBackgroundTintList(android.content.res.ColorStateList.valueOf(i==value?Ui.CORAL:Ui.SURFACE));steps[i].setTextSize(12);steps[i].setPadding(dp(3),dp(8),dp(3),dp(8));}
        if(value==2&&!running)search();updateButtons();
        if(value==1)selectionSummary.setText(t("Выбрано записей: ","Selected recordings: ")+selectedCount());
    }
    void enableTree(View view,boolean enabled){
        view.setEnabled(enabled);if(view instanceof ViewGroup){ViewGroup group=(ViewGroup)view;for(int i=0;i<group.getChildCount();i++)enableTree(group.getChildAt(i),enabled);}
    }
    int selectedCount(){int n=0;for(Library.Entry e:visible)if(e.selected)n++;return n;}
    void updateButtons(){
        if(run==null)return;
        enableTree(filesPage,!running&&!scanning);enableTree(queryPage,!running);
        back.setVisibility(stage==0?View.GONE:View.VISIBLE);stop.setVisibility(running?View.VISIBLE:View.GONE);stop.setEnabled(running);
        if(stage==0){run.setText(t("Далее: что найти","Next: what to find"));run.setEnabled(!scanning&&selectedCount()>0);}
        else if(stage==1){run.setText(t("Начать поиск","Start searching")+" ("+selectedCount()+")");run.setEnabled(!running&&selectedCount()>0&&query.getText().toString().trim().length()>0);}
        else {run.setText(t("Сохранить результаты CSV","Save results as CSV"));run.setEnabled(!matches.isEmpty());}
    }
    void refreshFiles(){
        if(fileAdapter==null)return;
        try{visible=filtered();fileAdapter.notifyDataSetChanged();updateCount();}
        catch(Exception e){visible.clear();fileAdapter.notifyDataSetChanged();count.setText(e.getMessage());updateButtons();}
    }
    void updateCount(){
        long bytes=0;for(Library.Entry e:visible)if(e.selected)bytes+=e.size;
        count.setText(t("В списке: ","Shown: ")+visible.size()+t("   Выбрано: ","   Selected: ")+selectedCount()+String.format(Locale.ROOT,"   %.1f MiB",bytes/1048576.0));
        updateButtons();
    }
    void bulk(boolean check){
        library.selectMany(visible,check);for(Library.Entry e:visible)e.selected=check;fileAdapter.notifyDataSetChanged();updateCount();
    }
    final class FileAdapter extends BaseAdapter {
        public int getCount(){return visible.size();}public Object getItem(int i){return visible.get(i);}public long getItemId(int i){return i;}
        public View getView(int index,View convert,ViewGroup parent){
            CheckBox box=convert instanceof CheckBox?(CheckBox)convert:new CheckBox(MainActivity.this);
            Ui.check(box);box.setTextSize(14);box.setPadding(dp(6),dp(9),dp(6),dp(9));
            Library.Entry e=visible.get(index);String modified=e.modified==0?t("Дата неизвестна","Unknown date"):new SimpleDateFormat("dd.MM.yyyy",Locale.ROOT).format(new Date(e.modified));
            box.setOnCheckedChangeListener(null);box.setChecked(e.selected);
            box.setText(e.name+"\n"+modified+String.format(Locale.ROOT,"   %.2f MiB",e.size/1048576.0)+
                    (!e.error.isEmpty()?t("   Ошибка","   Error"):!e.text.isEmpty()?t("   Текст готов","   Text ready"):""));
            box.setOnCheckedChangeListener((b,checked)->{library.select(e.uri,checked);e.selected=checked;anchor=index;updateCount();});
            box.setOnLongClickListener(v->{
                int first=anchor<0?index:Math.min(anchor,index),last=anchor<0?index:Math.max(anchor,index);
                library.selectMany(visible.subList(first,last+1),true);
                for(int k=first;k<=last;k++)visible.get(k).selected=true;
                notifyDataSetChanged();updateCount();return true;
            });box.setEnabled(!running&&!scanning);return box;
        }
    }
    final class ResultAdapter extends BaseAdapter {
        public int getCount(){return matches.size();}public Object getItem(int i){return matches.get(i);}public long getItemId(int i){return i;}
        public View getView(int index,View convert,ViewGroup parent){
            LinearLayout item=convert instanceof LinearLayout?(LinearLayout)convert:column();item.removeAllViews();Ui.panel(item);
            Result r=matches.get(index);
            TextView time=text(Search.time(r.start)+" – "+Search.time(r.end),14);time.setTextColor(Ui.CORAL);add(item,time);
            TextView name=text(r.file.name,14);name.setMaxLines(2);name.setEllipsize(TextUtils.TruncateAt.MIDDLE);add(item,name);
            add(item,text(r.excerpt,16));
            add(item,button(t("Прослушать и открыть контекст","Listen and view context"),()->details(r)));
            return item;
        }
    }
    void readProgress(){
        File file=new File(getFilesDir(),"progress.json");
        if(!file.isFile())return;
        try{
            JSONObject saved=new JSONObject(new String(Files.readAllBytes(file.toPath()),StandardCharsets.UTF_8));
            if(!saved.optBoolean("done",true)){
                boolean alive=false;
                for(ActivityManager.RunningServiceInfo info:((ActivityManager)getSystemService(ACTIVITY_SERVICE)).getRunningServices(100))
                    if(info.service.getClassName().equals(RecognitionService.class.getName()))alive=true;
                if(!alive)saved.put("done",true).put("message",t("Проверка прервана. Можно продолжить с готовым текстом.","Checking was interrupted. Resume using saved text."));
            }
            applyProgress(saved);
        }catch(Exception ignored){}
    }
    void applyProgress(JSONObject value){
        if(status==null||!activeJob.equals(value.optString("jobId")))return;boolean wasRunning=running;
        running=!value.optBoolean("done",true);
        status.setText(value.optString("message"));
        progressBar.setIndeterminate(running&&value.optInt("total")==0);
        progressBar.setProgress((int)(value.optDouble("fraction")*1000));
        double elapsed=value.optDouble("elapsed"),audio=value.optDouble("audioSeconds");
        String speed=elapsed>1&&audio>0?String.format(Locale.ROOT,t("   Скорость: %.1f×","   Speed: %.1f×"),audio/elapsed):"";
        long remaining=value.optLong("remaining",-1);
        metrics.setText(value.optInt("completed")+" / "+value.optInt("total")+t(" записей   Время: "," recordings   Elapsed: ")+Search.time(elapsed)+speed+
                (remaining>0?t("\nОсталось примерно ","\nAbout ")+Search.time(remaining)+t(" (оценка)"," remaining (estimate)"):""));
        StringBuilder names=new StringBuilder();JSONArray active=value.optJSONArray("active");
        if(active!=null)for(int i=0;i<active.length();i++){JSONObject p=active.optJSONObject(i);names.append(p.optString("name")).append("  ").append(Search.time(p.optDouble("seconds")));
            if(p.optDouble("duration")>0)names.append(" / ").append(Search.time(p.optDouble("duration")));names.append('\n');}
        activeFiles.setText(names.toString().trim());activeFiles.setVisibility(names.length()==0?View.GONE:View.VISIBLE);
        updateButtons();
        if(wasRunning&&!running){refreshFiles();search();}
    }
    Long date(EditText edit,boolean end)throws Exception{String s=edit.getText().toString().trim();if(s.isEmpty())return null;SimpleDateFormat f=new SimpleDateFormat("yyyy-MM-dd",Locale.ROOT);f.setLenient(false);ParsePosition p=new ParsePosition(0);Date d=f.parse(s,p);if(d==null||p.getIndex()!=s.length())throw new Exception(t("Проверьте дату: ГГГГ-ММ-ДД","Check date: YYYY-MM-DD"));Calendar c=Calendar.getInstance();c.setTime(d);if(end)c.add(Calendar.DATE,1);return c.getTimeInMillis();}
    double size(EditText edit,double fallback)throws Exception{String s=edit.getText().toString().trim().replace(',','.');if(s.isEmpty())return fallback;double v=Double.parseDouble(s);if(!Double.isFinite(v)||v<0)throw new Exception(t("Проверьте размер","Check size"));return v*1048576;}
    List<Library.Entry> filtered()throws Exception{Long from=date(dateFrom,false),to=date(dateTo,true);double min=size(sizeMin,0),max=size(sizeMax,Double.MAX_VALUE);if(from!=null&&to!=null&&from>=to||min>max)throw new Exception(t("Проверьте диапазон фильтра","Check filter range"));String name=nameFilter.getText().toString().toLowerCase(Locale.ROOT);List<Library.Entry> list=new ArrayList<>();for(Library.Entry e:library.entries()){boolean named=name.trim().isEmpty();for(String part:name.split(";"))if(!part.trim().isEmpty()&&e.name.toLowerCase(Locale.ROOT).contains(part.trim()))named=true;if(!named||e.size<min||e.size>max)continue;if(from!=null&&(e.modified==0||e.modified<from)||to!=null&&(e.modified==0||e.modified>=to))continue;list.add(e);}return list;}

    void permission(Uri uri,int flags){try{getContentResolver().takePersistableUriPermission(uri,flags&Intent.FLAG_GRANT_READ_URI_PERMISSION);}catch(SecurityException ignored){}}
    void add(Uri uri)throws Exception{String name="recording",mime="";long size=0,modified=0;try(Cursor c=getContentResolver().query(uri,null,null,null,null)){if(c!=null&&c.moveToFirst()){int col=c.getColumnIndex(OpenableColumns.DISPLAY_NAME);if(col>=0)name=c.getString(col);col=c.getColumnIndex(OpenableColumns.SIZE);if(col>=0)size=c.getLong(col);col=c.getColumnIndex(DocumentsContract.Document.COLUMN_LAST_MODIFIED);if(col>=0)modified=c.getLong(col);col=c.getColumnIndex(DocumentsContract.Document.COLUMN_MIME_TYPE);if(col>=0)mime=c.getString(col);}}if(mime!=null&&mime.startsWith("audio/")||name.toLowerCase(Locale.ROOT).matches(".*\\.(mp3|wav|m4a|aac|ogg|flac|mp4|wma)$"))library.add(uri.toString(),name,size,modified);}
    void tree(Uri tree,String parent,Set<String> seen)throws Exception{if(!seen.add(parent))return;if(seen.size()>10000)throw new IOException("Folder limit reached");Uri children=DocumentsContract.buildChildDocumentsUriUsingTree(tree,parent);try(Cursor c=getContentResolver().query(children,new String[]{DocumentsContract.Document.COLUMN_DOCUMENT_ID,DocumentsContract.Document.COLUMN_MIME_TYPE},null,null,null)){if(c!=null)while(c.moveToNext()){String id=c.getString(0);if(DocumentsContract.Document.MIME_TYPE_DIR.equals(c.getString(1)))tree(tree,id,seen);else add(DocumentsContract.buildDocumentUriUsingTree(tree,id));}}}
    @Override protected void onActivityResult(int request,int result,Intent data){super.onActivityResult(request,result,data);if(result!=RESULT_OK||data==null)return;if(request==EXPORT){try(OutputStream out=getContentResolver().openOutputStream(data.getData(),"wt")){out.write(csv.getBytes(StandardCharsets.UTF_8));toast(t("Таблица сохранена","Table saved"));}catch(Exception e){toast(e.getMessage());}return;}
        List<Uri> uris=new ArrayList<>();if(data.getClipData()!=null)for(int i=0;i<data.getClipData().getItemCount();i++)uris.add(data.getClipData().getItemAt(i).getUri());else if(data.getData()!=null)uris.add(data.getData());for(Uri uri:uris)permission(uri,data.getFlags());
        scanning=true;updateButtons();toast(t("Читаем список файлов…","Reading file list…"));new Thread(()->{String error=null;try{for(Uri uri:uris)if(request==TREE)tree(uri,DocumentsContract.getTreeDocumentId(uri),new HashSet<>());else add(uri);}catch(Exception e){error=e.getMessage();}String message=error;runOnUiThread(()->{scanning=false;refreshFiles();updateButtons();if(message!=null)toast(message);});}).start();
    }

    void details(Result r){JSONArray segments=r.file.segments();StringBuilder context=new StringBuilder();double end=r.end;for(int i=0;i<segments.length();i++){JSONObject s=segments.optJSONObject(i);if(s.optDouble("end")<r.start-10||s.optDouble("start")>r.end+30)continue;context.append(Search.time(s.optDouble("start"))).append("  ").append(s.optString("text")).append("\n\n");end=Math.max(end,s.optDouble("end"));}double finish=end;TextView content=text(t("Ближайшие реплики: 10 секунд до и 30 после. Границы темы определите по разговору.\n\n","Nearby speech: 10 seconds before and 30 after. Check the conversation to determine topic boundaries.\n\n")+context,16);content.setTextIsSelectable(true);content.setPadding(dp(18),dp(8),dp(18),dp(8));ScrollView scroll=new ScrollView(this);scroll.addView(content);AlertDialog dialog=new AlertDialog.Builder(this).setTitle(r.file.name).setView(scroll).setPositiveButton(t("Слушать","Play"),null).setNeutralButton(t("Стоп","Stop"),(d,w)->stopAudio()).setNegativeButton(t("Закрыть","Close"),(d,w)->stopAudio()).create();dialog.setOnDismissListener(d->stopAudio());dialog.setOnShowListener(d->dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v->play(r.file.uri,r.start,finish)));dialog.show();}
    void play(String uri,double start,double end){stopAudio();try{player=new MediaPlayer();player.setDataSource(this,Uri.parse(uri));player.setOnPreparedListener(p->{p.seekTo((long)(start*1000),MediaPlayer.SEEK_CLOSEST);p.start();handler.postDelayed(this::stopAudio,(long)((end-start)*1000));});player.setOnCompletionListener(p->stopAudio());player.setOnErrorListener((p,a,b)->{toast(t("Не удалось воспроизвести","Could not play audio"));stopAudio();return true;});player.prepareAsync();}catch(Exception e){toast(e.getMessage());stopAudio();}}
    void stopAudio(){handler.removeCallbacksAndMessages(null);if(player!=null){player.release();player=null;}}
    void export(){if(matches.isEmpty()){toast(t("Нет результатов для экспорта","No results to export"));return;}StringBuilder out=new StringBuilder("\uFEFF");String[] columns=language.equals("ru")?new String[]{"Файл","Время в записи","Фрагмент разговора","Кратко (цитата)"}:new String[]{"File","Time in recording","Conversation excerpt","Brief (quote)"};for(int i=0;i<4;i++)out.append(i==0?"":",").append(Search.csv(columns[i]));out.append("\r\n");for(Result r:matches)out.append(Search.csv(r.file.name)).append(',').append(Search.csv(Search.time(r.start)+"–"+Search.time(r.end))).append(',').append(Search.csv(r.excerpt)).append(',').append(Search.csv(r.summary)).append("\r\n");csv=out.toString();startActivityForResult(new Intent(Intent.ACTION_CREATE_DOCUMENT).setType("text/csv").addCategory(Intent.CATEGORY_OPENABLE).putExtra(Intent.EXTRA_TITLE,"AudioDetect-results.csv"),EXPORT);}
    void toast(String message){Toast.makeText(this,message,Toast.LENGTH_LONG).show();}

    void start(){
        if(running||scanning)return;
        if(query.getText().toString().trim().isEmpty()){showStage(1);query.requestFocus();query.setError(t("Введите слова для поиска","Enter words to search for"));return;}
        try {
            JSONArray uris=new JSONArray();for(Library.Entry e:filtered())if(e.selected)uris.put(e.uri);
            if(uris.length()==0){showStage(0);toast(t("Выберите хотя бы одну запись","Select at least one recording"));return;}
            getPreferences(0).edit().putString("query",query.getText().toString()).putInt("mode",mode.getSelectedItemPosition())
                .putInt("speech",speech.getSelectedItemPosition()).putBoolean("economical",economical.isChecked()).apply();
            activeJob=UUID.randomUUID().toString();getPreferences(0).edit().putString("jobId",activeJob).apply();
            JSONObject job=new JSONObject().put("jobId",activeJob).put("language",speech.getSelectedItemPosition()==0?"ru":"en")
                .put("uris",uris).put("economical",economical.isChecked());
            Files.write(new File(getFilesDir(),"job.json").toPath(),job.toString().getBytes(StandardCharsets.UTF_8));
            if(Build.VERSION.SDK_INT>=33&&checkSelfPermission("android.permission.POST_NOTIFICATIONS")!=0)
                requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"},13);
            showStage(2);running=true;resume.setVisibility(View.GONE);
            status.setText(t("Проверяем готовый текст и новые записи…","Checking saved text and new recordings…"));
            progressBar.setIndeterminate(true);metrics.setText("");activeFiles.setText("");updateButtons();
            startForegroundService(new Intent(this,RecognitionService.class).putExtra("uiLanguage",language).putExtra("jobId",activeJob));
        } catch(Exception e){running=false;updateButtons();toast(e.getMessage());}
    }
    void stop(){
        if(running){startService(new Intent(this,RecognitionService.class).setAction("STOP"));stop.setEnabled(false);
            status.setText(t("Останавливаем. Готовый текст сохранён.","Stopping. Completed text is saved."));}
    }
    int searchGeneration=0;
    boolean destroyed=false;
    void search(){
        if(resultList==null)return;
        int generation=++searchGeneration;
        String q=query.getText().toString().trim();
        matches.clear();resultAdapter.notifyDataSetChanged();updateButtons();
        if(q.isEmpty()){resultsCount.setText("");emptyResults.setText(t("Задайте запрос на шаге 2, чтобы увидеть найденные фрагменты.",
                "Enter a query in step 2 to see matching excerpts."));return;}
        int searchMode=mode.getSelectedItemPosition();boolean allowFuzzy=fuzzy.isChecked();
        String lang=speech.getSelectedItemPosition()==0?"ru":"en";
        final List<Library.Entry> scope;
        try{scope=filtered();}catch(Exception e){toast(e.getMessage());return;}
        emptyResults.setText(t("Ищем в готовом тексте…","Searching saved text…"));
        new Thread(()->{
            List<Result> found=new ArrayList<>();int ready=0,pending=0,files=0,failed=0;
            try{
                for(Library.Entry e:scope){
                    if(!e.selected)continue;
                    if(!e.error.isEmpty()){failed++;pending++;continue;}
                    if(e.text.isEmpty()||!e.language.equals(lang)){pending++;continue;}
                    ready++;
                    if(searchMode>0&&!Search.matches(e.words(),q,searchMode,allowFuzzy))continue;
                    JSONArray parts=e.segments();int before=found.size();
                    for(int i=0;i<parts.length();i++){
                        JSONObject part=parts.getJSONObject(i);String excerpt=part.getString("text");
                        double start=part.getDouble("start"),end=part.getDouble("end");
                        boolean hit=Search.matches(excerpt,q,searchMode==1?2:searchMode,allowFuzzy);
                        if(searchMode==0&&!hit&&i+1<parts.length()){
                            JSONObject next=parts.getJSONObject(i+1);
                            if(next.getDouble("start")-end<=8&&next.getDouble("end")-start<=45&&
                                    Search.matches(excerpt+" "+next.getString("text"),q,0,allowFuzzy)){
                                hit=true;excerpt+=" "+next.getString("text");end=next.getDouble("end");
                            }
                        }
                        if(hit)found.add(new Result(e,start,end,excerpt));
                    }
                    if(found.size()>before)files++;
                }
                int completed=ready,remaining=pending,matchingFiles=files,errorCount=failed;
                runOnUiThread(()->{
                    if(destroyed||generation!=searchGeneration)return;
                    matches.addAll(found);resultAdapter.notifyDataSetChanged();
                    resultsCount.setText(t("Найдено записей: ","Matching recordings: ")+matchingFiles+t("   Фрагментов: ","   Excerpts: ")+found.size());
                    emptyResults.setText(remaining>0?
                        t("В готовом тексте совпадений пока нет.\nОсталось проверить записей: ","No matches in the ready text yet.\nRecordings left to check: ")+remaining:
                        t("Совпадений не найдено.\nВсе выбранные записи проверены. Попробуйте другое слово или режим «Хотя бы одно слово».",
                        "No matches found.\nAll selected recordings were checked. Try another word or “Any of these words”."));
                    resume.setVisibility(!running&&remaining>0?View.VISIBLE:View.GONE);
                    if(!running&&metrics.getText().length()==0)metrics.setText(t("Готовый текст: ","Saved transcripts: ")+completed+t("   Ошибок: ","   Errors: ")+errorCount);
                    updateButtons();
                });
            }catch(Exception e){runOnUiThread(()->{if(!destroyed&&generation==searchGeneration)toast(e.getMessage());});}
        },"text-search").start();
    }
    @Override protected void onDestroy(){
        destroyed=true;searchGeneration++;progressHandler.removeCallbacksAndMessages(null);
        unregisterReceiver(events);stopAudio();if(library!=null)library.close();super.onDestroy();
    }
}
