# thinkitup
Preprocessing on thinkorswim's thinkscript syntax, add basic macros and .ts file imports; it's basic and raw, but it does make life easier.

Presently assumes all relevant and importable files are within the current directory when run.

Also assumes said directory is that of this repository; working on that next.

Actually, working on getting a basic, displayable example for the README next, because this thing is confusing.

## Things it can do

- **@import**
  - import the processed contents of another file
  - useful for including the full contents of library files full of script/functions
- **@\<macro-definition\>(...)**
  - can't stand the inability to generically assign style values to plots
  - this gets around that by brute, macro-replacement force
- **@if**
  - hide blocks of text if `@if 0` or `@if false`
  - there are also others like `@if import` or `@if noimport`
- **@main**
  - this grabs a block of input declarations in a script/function
    - then outputs them at the end of the file with a `plot z_<script-name> = <script-name>(...)`

## Beware

Honestly, this thing is a mess I threw together after boiling over in frustration over thinkscript's lack of various basic syntax functionalities.

I'll... pretty it up at some point, but I only tossed it up on github in case others may stumble upon it and be inspired to make something a little more solid.
