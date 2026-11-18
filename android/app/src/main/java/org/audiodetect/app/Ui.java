package org.audiodetect.app;

import android.content.Context;
import android.content.res.ColorStateList;
import android.graphics.*;
import android.graphics.drawable.*;
import android.view.View;
import android.widget.*;

/** Coral light over deep green surfaces, with readable native controls. */
final class Ui {
    static final int BG=Color.rgb(20,44,47), SURFACE=Color.rgb(32,61,63),
            RAISED=Color.rgb(43,73,73), LINE=Color.rgb(84,113,110),
            TEXT=Color.rgb(241,242,224), MUTED=Color.rgb(184,201,193),
            CORAL=Color.rgb(255,159,143), INK=Color.rgb(42,43,38),
            DISABLED=Color.rgb(66,83,79);
    static int dp(Context c,int n){return Math.round(n*c.getResources().getDisplayMetrics().density);}
    static GradientDrawable surface(Context c,int color,int border,int radius) {
        GradientDrawable d=new GradientDrawable();
        d.setColor(color);d.setCornerRadius(dp(c,radius));d.setStroke(dp(c,1),border);return d;
    }
    static Drawable background() {
        return new GradientDrawable(GradientDrawable.Orientation.TL_BR,
                new int[]{Color.rgb(84,69,59),Color.rgb(31,62,62),BG});
    }
    static void panel(View view) {
        Context c=view.getContext();
        view.setBackground(surface(c,SURFACE,LINE,14));
        view.setElevation(dp(c,3));
        view.setPadding(dp(c,18),dp(c,16),dp(c,18),dp(c,16));
    }
    static void text(TextView view,int size,boolean muted) {
        view.setTextColor(muted?MUTED:TEXT);view.setTextSize(size);
        view.setFontFeatureSettings("kern");
    }
    static void button(Button button,boolean primary) {
        Context c=button.getContext();
        StateListDrawable states=new StateListDrawable();
        states.addState(new int[]{-android.R.attr.state_enabled},surface(c,DISABLED,DISABLED,10));
        states.addState(new int[]{android.R.attr.state_pressed},surface(c,primary?0xFFFFB7A8:RAISED,CORAL,10));
        states.addState(new int[]{android.R.attr.state_focused},surface(c,primary?CORAL:RAISED,CORAL,10));
        states.addState(new int[]{},surface(c,primary?CORAL:SURFACE,primary?0xFFFFC7B9:LINE,10));
        states.setState(button.getDrawableState());
        button.setBackgroundTintList(null);
        button.setBackground(new RippleDrawable(ColorStateList.valueOf(0x33FFFFFF),states,null));
        button.setBackgroundTintList(null);
        button.setTextColor(new ColorStateList(new int[][]{new int[]{-android.R.attr.state_enabled},new int[]{}},
                new int[]{MUTED,primary?INK:TEXT}));
        button.setAllCaps(false);button.setTextSize(14);
        button.setMinHeight(dp(c,50));button.setMinimumHeight(dp(c,50));
        button.setPadding(dp(c,14),dp(c,10),dp(c,14),dp(c,10));
        button.setElevation(dp(c,primary?5:2));
        button.setTypeface(null,primary?android.graphics.Typeface.BOLD:android.graphics.Typeface.NORMAL);
    }
    static void input(EditText edit) {
        Context c=edit.getContext();
        StateListDrawable states=new StateListDrawable();
        states.addState(new int[]{android.R.attr.state_focused},surface(c,BG,CORAL,10));
        states.addState(new int[]{},surface(c,BG,LINE,10));
        edit.setBackground(states);edit.setTextColor(TEXT);edit.setHintTextColor(MUTED);
        edit.setPadding(dp(c,14),dp(c,13),dp(c,14),dp(c,13));
        edit.setMinimumHeight(dp(c,52));edit.setTextSize(16);edit.setSelectAllOnFocus(false);
    }
    static void check(CheckBox check) {
        check.setTextColor(TEXT);check.setButtonTintList(new ColorStateList(
                new int[][]{new int[]{android.R.attr.state_checked},new int[]{}},
                new int[]{CORAL,MUTED}));check.setMinHeight(dp(check.getContext(),48));
    }
    static void spinner(Spinner spinner,String[] values) {
        Context c=spinner.getContext();
        ArrayAdapter<String> adapter=new ArrayAdapter<String>(c,android.R.layout.simple_spinner_dropdown_item,values){
            @Override public View getView(int position,View convert,android.view.ViewGroup parent) {
                TextView view=(TextView)super.getView(position,convert,parent);
                view.setText(values[position]+"  \u25be");view.setTextColor(TEXT);view.setTextSize(15);view.setPadding(dp(c,12),dp(c,14),dp(c,28),dp(c,14));return view;
            }
            @Override public View getDropDownView(int position,View convert,android.view.ViewGroup parent) {
                TextView view=(TextView)super.getDropDownView(position,convert,parent);
                view.setTextColor(TEXT);view.setBackgroundColor(SURFACE);
                view.setPadding(dp(c,14),dp(c,16),dp(c,14),dp(c,16));return view;
            }
        };
        spinner.setAdapter(adapter);spinner.setBackground(surface(c,BG,LINE,10));
        spinner.setPopupBackgroundDrawable(surface(c,SURFACE,LINE,10));
        spinner.setMinimumHeight(dp(c,52));
    }
}
