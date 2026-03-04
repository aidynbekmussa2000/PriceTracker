#!/usr/bin/env python3
"""Format claude streaming JSON into readable output for FastMCP AI Agent project."""
import sys
import json

COLORS = {
    'reset': '\033[0m',
    'bold': '\033[1m',
    'dim': '\033[2m',
    'blue': '\033[34m',
    'green': '\033[32m',
    'yellow': '\033[33m',
    'cyan': '\033[36m',
    'magenta': '\033[35m',
    'red': '\033[31m',
}

def c(color, text):
    return f"{COLORS.get(color, '')}{text}{COLORS['reset']}"

def format_message(data):
    msg_type = data.get('type')

    if msg_type == 'assistant':
        msg = data.get('message', {})
        content = msg.get('content', [])

        for item in content:
            if item.get('type') == 'text':
                text = item.get('text', '')
                if text.strip():
                    print(c('cyan', '  ') + text)

            elif item.get('type') == 'tool_use':
                tool = item.get('name', 'unknown')
                inp = item.get('input', {})

                # Color-code by tool category
                if tool.startswith('mcp__context7'):
                    color = 'magenta'
                    icon = '\U0001f4da'
                elif tool.startswith('mcp__playwright'):
                    color = 'blue'
                    icon = '\U0001f3ad'
                elif tool == 'WebFetch':
                    color = 'blue'
                    icon = '\U0001f310'
                elif tool in ('Read', 'Write', 'Edit', 'Glob', 'Grep'):
                    color = 'yellow'
                    icon = '\U0001f4c1'
                elif tool == 'Bash':
                    color = 'green'
                    icon = '\u26a1'
                elif tool == 'NotebookEdit':
                    color = 'cyan'
                    icon = '\U0001f4d3'
                else:
                    color = 'yellow'
                    icon = '\U0001f527'

                print(c(color, f'{icon} {tool}'), end='')

                # Show key details based on tool
                if tool == 'Read':
                    print(c('dim', f" \u2192 {inp.get('file_path', '')}"))
                elif tool == 'Write':
                    print(c('dim', f" \u2192 {inp.get('file_path', '')}"))
                elif tool == 'Edit':
                    print(c('dim', f" \u2192 {inp.get('file_path', '')}"))
                elif tool == 'Bash':
                    cmd = inp.get('command', '')[:80]
                    print(c('dim', f" \u2192 {cmd}"))
                elif tool == 'Grep':
                    print(c('dim', f" \u2192 pattern: {inp.get('pattern', '')}"))
                elif tool == 'Glob':
                    print(c('dim', f" \u2192 {inp.get('pattern', '')}"))
                elif tool == 'WebFetch':
                    url = inp.get('url', '')[:60]
                    print(c('dim', f" \u2192 {url}"))
                elif tool == 'NotebookEdit':
                    mode = inp.get('edit_mode', 'replace')
                    print(c('dim', f" \u2192 {mode}"))
                elif 'context7' in tool:
                    lib = inp.get('libraryName', inp.get('context7CompatibleLibraryID', ''))
                    query = inp.get('query', '')[:40]
                    print(c('dim', f" \u2192 {lib} | {query}"))
                elif 'playwright' in tool:
                    action = tool.split('__')[-1] if '__' in tool else tool
                    url = inp.get('url', inp.get('selector', ''))[:50]
                    print(c('dim', f" \u2192 {action}: {url}"))
                else:
                    if inp:
                        key = list(inp.keys())[0]
                        val = str(inp[key])[:50]
                        print(c('dim', f" \u2192 {key}: {val}"))
                    else:
                        print()

    elif msg_type == 'user':
        msg = data.get('message', {})
        content = msg.get('content', [])

        for item in content:
            if item.get('type') == 'tool_result':
                result = data.get('tool_use_result', {})
                if isinstance(result, str):
                    if len(result) > 100:
                        print(c('green', '  \u2713 ') + c('dim', f"result: {len(result)} chars"))
                    elif result.strip():
                        print(c('green', '  \u2713 ') + c('dim', result[:100]))
                elif isinstance(result, dict):
                    if result.get('file'):
                        print(c('green', '  \u2713 ') + c('dim', f"read {result['file'].get('numLines', '?')} lines"))
                    elif result.get('numFiles') is not None:
                        print(c('green', '  \u2713 ') + c('dim', f"found {result['numFiles']} files"))
                    else:
                        content_str = item.get('content', '')
                        if len(content_str) > 100:
                            print(c('green', '  \u2713 ') + c('dim', f"result: {len(content_str)} chars"))
                        elif content_str.strip():
                            print(c('green', '  \u2713 ') + c('dim', content_str[:100]))
                else:
                    print(c('green', '  \u2713 '))

    elif msg_type == 'result':
        result = data.get('result', '')
        if result:
            print(c('bold', '\n\u2501\u2501\u2501 RESULT \u2501\u2501\u2501'))
            print(result)

def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            format_message(data)
        except json.JSONDecodeError:
            # Not JSON, print as-is
            print(line)

if __name__ == '__main__':
    main()
