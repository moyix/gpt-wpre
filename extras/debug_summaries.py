#!/usr/bin/env python

import json
import subprocess
import sys
import textwrap
import shutil
from io import StringIO

from pygments import highlight, lexers, formatters
from pygments.token import Token

# These would need to be adjusted for your system / program
base_addr = 0x100000
if shutil.which('gaddr2line') is None:
    addr2line = '/usr/local/Cellar/binutils/2.35/bin/gaddr2line'
if shutil.which('gnm') is None:
    nm = '/usr/local/Cellar/binutils/2.35/bin/gnm'

# Ditto
FILE_FROM = '/home/moyix/git/codex_add_assertions/'
FILE_TO = 'samples/srcs/'
def reloc(file):
    if file.startswith(FILE_FROM):
        return FILE_TO + file[len(FILE_FROM):]
    return file

# Change for your terminal width if desired
COLUMNS = 164
BOX_WIDTH = 70

# XXX: this is a very hacky way to pull out the source code for a function
#      and it is certain to fail on anything except libpng. But I'll be
#      damned if I'm going to lose another week of my ever-dwindling life
#      to wrestling with tree-sitter.
def func_source(func_name, src_file):
    with open(src_file) as f:
        lines = f.readlines()
    start = None
    end = None
    for i, line in enumerate(lines):
        if start is None and line.startswith(func_name):
            start = i
        if start is not None and line.startswith('}'):
            end = i
            break
    if start is None or end is None:
        return None
    # Move start back to last blank line
    while start > 0 and lines[start-1].strip() != '':
        start -= 1
    # Move end forward to next blank line
    while end < len(lines) and lines[end+1].strip() != '':
        end += 1
    return ''.join(lines[start:end+1])

def get_syms_from_nm(binary):
    p = subprocess.Popen([nm, '-n', binary], stdout=subprocess.PIPE, text=True)
    out, err = p.communicate()
    syms = {}
    for line in out.splitlines():
        addr = line[:16].strip()
        if addr == '':
            continue
        addr = int(addr, 16)
        name = line[19:].strip()
        syms[name] = addr
    return syms

def lookup_addrs(binary, funcs):
    syms = get_syms_from_nm(binary)
    name_map = {}
    names = []
    addrs = []
    for func in funcs:
        if func.startswith('FUN_'):
            addr = int(func[4:], 16) - base_addr
            addrs.append(addr)
            names.append(func)
        else:
            addr = syms[func]
            addrs.append(addr)
            names.append(func)
    addrs = [hex(addr) for addr in addrs]
    p = subprocess.Popen([addr2line, '-a', '-f', '-e', binary],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    out, err = p.communicate("\n".join(addrs))
    # Output is in the form:
    #   <addr>
    #   <function>
    #   <file>:<line>
    lines = out.splitlines()
    symbols = []
    for i in range(0, len(lines), 3):
        addr = int(lines[i], 16)
        func = lines[i+1]
        file, line = lines[i+2].split(':')
        symbols.append( (addr, func, file, line) )
    for name, (addr, func, file, line) in zip(names, symbols):
        name_map[name] = (func, file, line)
    return name_map

def side_by_side_highlight(title1, title2, code1, code2, lexer, formatter, width=(COLUMNS-4)//2):
    # Strip trailing whitespace up front so we don't have to worry about it
    code1 = code1.strip()
    code2 = code2.strip()
    code1 = '\n'.join(l.rstrip() for l in code1.split('\n'))
    code2 = '\n'.join(l.rstrip() for l in code2.split('\n'))

    code1_lines = code1.split('\n')
    code2_lines = code2.split('\n')
    hcode1_lines = highlight(code1, lexer, formatter).rstrip().split('\n')
    hcode2_lines = highlight(code2, lexer, formatter).rstrip().split('\n')
    assert len(code1_lines) == len(hcode1_lines)
    assert len(code2_lines) == len(hcode2_lines)

    # Print the titles centered in each column
    print(title1.center(width) + ' | ' + title2.center(width))
    print('-'*(width*2+3))
    for i in range(max(len(code1_lines), len(code2_lines))):
        line1 = code1_lines[i] if i < len(code1_lines) else ''
        line2 = code2_lines[i] if i < len(code2_lines) else ''
        hline1 = hcode1_lines[i] if i < len(hcode1_lines) else ''
        hline2 = hcode2_lines[i] if i < len(hcode2_lines) else ''
        # Use the unhighlighted lines to determine how much to pad
        pad = width - len(line1)
        print(hline1 + ' '*pad + ' | ' + hline2)

def main():
    if len(sys.argv) < 4:
        print(f'Usage: {sys.argv[0]} <binary> <summaries.json> <decompilations.json>')
        sys.exit(1)

    formatter = formatters.Terminal256Formatter(style='monokai')
    lexer = lexers.get_lexer_by_name('c')
    def bold(s):
        sio = StringIO()
        formatter.format([(Token.Generic.Strong, s)], sio)
        return sio.getvalue()

    binary = sys.argv[1]
    summaries = {}
    with open(sys.argv[2]) as f:
        for line in f:
            summaries.update(json.loads(line))
    with open(sys.argv[3]) as f:
        decompilations = json.load(f)

    name_map = lookup_addrs(binary, summaries.keys())
    for func, summary in summaries.items():
        real_name, src_file, src_line = name_map[func]
        print(f' {func} '.center(COLUMNS, '='))
        print()
        print(f'Real name: {real_name}'.center(COLUMNS))
        print()
        print(bold('OpenAI text-davinci-003 Summary'.center(COLUMNS)))
        # Print the summary, wrapped at BOX_WIDTH columns, in a box
        summary = textwrap.fill(summary.strip(), BOX_WIDTH)
        left_pad = ' '*((COLUMNS-(BOX_WIDTH+4))//2)
        box_line = left_pad + '+' + '-'*(BOX_WIDTH+2) + '+'
        print(box_line)
        for line in summary.splitlines():
            print(left_pad + '| ' + bold(line.ljust(BOX_WIDTH)) + ' |')
        print(box_line)
        print()
        if src_file:
            relpath = src_file.replace(FILE_FROM, '')
            reloc_sf = reloc(src_file)
            code = func_source(real_name, reloc_sf)
            if not code:
                print(f'Failed to find source for {real_name}')
                continue
            decomp = decompilations.get(func, None)
            if not decomp:
                print(f'Failed to find decompilation for {func}')
                continue
            side_by_side_highlight(f'{relpath}:{src_line}', f'Decompilation: {func}', code, decomp, lexer, formatter)
        print()

if __name__ == '__main__':
    main()

