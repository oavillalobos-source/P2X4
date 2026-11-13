"""Original website docking activity illustration, driven by reported job stage."""
from pathlib import Path

def animation_html(step):
    stage = step if step in ('docking', 'analyzing') else 'preparing'
    html = Path(__file__).with_suffix('.html').read_text()
    return (html.replace('__STEP__', stage)
            .replace('__PREP__', 'active' if stage == 'preparing' else '')
            .replace('__DOCK__', 'active' if stage == 'docking' else '')
            .replace('__ANALYZE__', 'active' if stage == 'analyzing' else ''))

def render(step='preparing'):
    import streamlit.components.v1 as components
    components.html(animation_html(step), height=245, scrolling=False)
