"""Curated citation guidance; no researcher data or inferred authorship."""
from datetime import date

REFERENCES = []
def article(key, label, authors, year, title, journal, abbr, volume, pages, doi, scope='Core docking'):
    apa_names = [f'{surname}, {initials}' for surname, initials in authors]
    apa_author = ', '.join(apa_names[:-1]) + ', & ' + apa_names[-1] if len(authors)>1 else apa_names[0]
    ama_author = ', '.join(surname+' '+initials.replace('.', '').replace(' ', '') for surname, initials in authors)
    REFERENCES.append(dict(id=key, label=label, scope=scope,
        apa=f'{apa_author} ({year}). {title}. {journal}, {volume}, {pages}. https://doi.org/{doi}',
        ama=f'{ama_author}. {title}. {abbr}. {year};{volume}:{pages}. doi:{doi}', url=f'https://doi.org/{doi}'))

def software(key, title, url, scope):
    REFERENCES.append(dict(id=key, label=title, scope=scope,
        apa=f'{title} [Computer software]. (n.d.). {url}',
        ama=f'{title}. Computer software. Accessed {{accessed}}. {url}', url=url))

software('platform', 'P2X4 Dock: Experimental live docking workspace', 'https://p2x4-live.streamlit.app/', 'Platform — provisional title-led citation')
article('vina', 'AutoDock Vina 1.2 — scores and poses', [('Eberhardt','J.'),('Santos-Martins','D.'),('Tillack','A. F.'),('Forli','S.')],2021,'AutoDock Vina 1.2.0: New docking methods, expanded force field, and Python bindings','Journal of Chemical Information and Modeling','J Chem Inf Model','61(8)','3891–3898','10.1021/acs.jcim.1c00203')
article('vina_original', 'Original AutoDock Vina method', [('Trott','O.'),('Olson','A. J.')],2010,'AutoDock Vina: Improving the speed and accuracy of docking with a new scoring function, efficient optimization, and multithreading','Journal of Computational Chemistry','J Comput Chem','31(2)','455–461','10.1002/jcc.21334')
article('structure', 'Human P2X4 structural study', [('Shi','H.'),('Ditter','I. A.'),('Oken','A. C.'),('Mansoor','S. E.')],2025,'Human P2X4 receptor gating is modulated by a stable cytoplasmic cap and a unique allosteric pocket','Science Advances','Sci Adv','11(3)','eadr3315','10.1126/sciadv.adr3315')
REFERENCES.append(dict(id='9bqi',label='PDB 9BQI — receptor coordinates',scope='Core docking',url='https://doi.org/10.2210/pdb9BQI/pdb',apa='Shi, H., Ditter, I. A., Oken, A. C., & Mansoor, S. E. (2025). Cryo-EM structure of BAY-1797 bound to the full-length human P2X4 receptor in the closed state (9BQI) [Data set]. Worldwide Protein Data Bank. https://doi.org/10.2210/pdb9BQI/pdb',ama='Shi H, Ditter IA, Oken AC, Mansoor SE. Cryo-EM structure of BAY-1797 bound to the full-length human P2X4 receptor in the closed state. 9BQI. Worldwide Protein Data Bank; 2025. doi:10.2210/pdb9BQI/pdb'))
article('dimorphite','Dimorphite-DL — protonation states',[('Ropp','P. J.'),('Kaminsky','J. C.'),('Yablonski','S.'),('Durrant','J. D.')],2019,'Dimorphite-DL: An open-source program for enumerating the ionization states of drug-like small molecules','Journal of Cheminformatics','J Cheminform','11','14','10.1186/s13321-019-0336-9')
software('rdkit','RDKit: Open-source cheminformatics','https://www.rdkit.org/','Core preparation, identity, descriptors and structure drawings')
software('meeko','Meeko','https://github.com/forlilab/Meeko','Core ligand preparation and pose export')
article('etkdg','ETKDGv3 — conformer generation',[('Wang','S.'),('Witek','J.'),('Landrum','G. A.'),('Riniker','S.')],2020,'Improving conformer generation for small rings and macrocycles based on distance geometry and experimental torsional-angle preferences','Journal of Chemical Information and Modeling','J Chem Inf Model','60(4)','2044–2058','10.1021/acs.jcim.0c00025')
article('mmff','MMFF94 — when reported in preparation log',[('Halgren','T. A.')],1996,'Merck molecular force field. I. Basis, form, scope, parameterization, and performance of MMFF94','Journal of Computational Chemistry','J Comput Chem','17(5–6)','490–519','10.1002/(SICI)1096-987X(199604)17:5/6<490::AID-JCC1>3.0.CO;2-P','Conditional: MMFF94 optimization')
article('uff','UFF — only when the fallback was used',[('Rappé','A. K.'),('Casewit','C. J.'),('Colwell','K. S.'),('Goddard III','W. A.'),('Skiff','W. M.')],1992,'UFF, a full periodic table force field for molecular mechanics and molecular dynamics simulations','Journal of the American Chemical Society','J Am Chem Soc','114(25)','10024–10035','10.1021/ja00051a040','Conditional: UFF optimization')
article('qed','QED — calculated drug-likeness',[('Bickerton','G. R.'),('Paolini','G. V.'),('Besnard','J.'),('Muresan','S.'),('Hopkins','A. L.')],2012,'Quantifying the chemical beauty of drugs','Nature Chemistry','Nat Chem','4(2)','90–98','10.1038/nchem.1243','Descriptors: cite when reporting QED')
article('prolif','ProLIF — optional interaction fingerprints',[('Bouysset','C.'),('Fiorucci','S.')],2021,'ProLIF: A library to encode molecular interactions as fingerprints','Journal of Cheminformatics','J Cheminform','13','72','10.1186/s13321-021-00548-6','Optional external analysis; not enabled in this live edition')
DEFAULT_IDS = [r['id'] for r in REFERENCES if r['id'] not in {'mmff','uff','prolif'}]

def bibliography(ids, style, accessed=None):
    if style not in ('APA', 'AMA'):
        raise ValueError('Choose APA or AMA')
    selected = [r for r in REFERENCES if r['id'] in ids]
    if style == 'APA':
        selected.sort(key=lambda r:r['apa'].casefold())
    when = (accessed or date.today()).strftime('%B %d, %Y')
    return '\n\n'.join((f'{i}. ' if style=='AMA' else '') + r[style.lower()].replace('{accessed}', when) for i,r in enumerate(selected,1))

def render():
    import streamlit as st
    st.title('How to cite')
    st.write('Credit the platform, the methods actually used, the receptor coordinates, and the original sources of your compounds and experimental labels.')
    st.info('Platform citation is provisional and title-led: an official author list, release date and archived release DOI have not been established here. Do not invent a paper or DOI. Record the exact software release/commit used with your methods.')
    style = st.radio('Citation style', ['APA', 'AMA'], horizontal=True)
    selected = st.multiselect('Include references for the data you report', [r['id'] for r in REFERENCES], default=DEFAULT_IDS, format_func=lambda key:next(r['label'] for r in REFERENCES if r['id']==key))
    st.caption('APA 7: alphabetical bibliography. AMA: numbers below follow this selection; renumber by first appearance in your manuscript. Confirm MMFF94 versus UFF in each preparation log. Software citations require the version actually used, not the current website version.')
    text = bibliography(selected, style)
    st.text_area('Copy-ready bibliography', text, height=400)
    st.download_button(f'Download {style} references (.txt)',text, f'p2x4-references-{style.lower()}.txt',mime='text/plain')
    with st.expander('Which reference supports each output?', expanded=True):
        for r in REFERENCES:
            st.markdown(f"**{r['label']}** — {r['scope']}")
            st.link_button('Source: '+r['id'],r['url'])
    with st.expander('Cite your generated dataset, figures and validation results'):
        st.write('Your generated results are a separate research dataset. Archive the approved evidence ZIPs and tables in an appropriate repository, obtain a persistent identifier, and credit the actual dataset creators. A private registry URL or temporary job link is not a stable dataset citation.')
        st.code('APA template — replace every bracketed field:\n[Authors]. ([Year]). [Dataset title] (Version [version]) [Data set]. [Repository]. [DOI or persistent URL]\n\nAMA template — replace every bracketed field:\n[Authors]. [Dataset title]. Version [version]. [Repository]; [Year]. [DOI or persistent URL]')
        st.write('For each table or figure, retain compound codes and supplied names, standardized isomeric SMILES, job IDs, run date, software versions/commit, receptor PDB ID and preparation, box, seeds, exhaustiveness, microspecies settings, scoring/consensus rule version and evidence checksums. Cite both the dataset and the methods producing that panel.')
        st.write('Native-contact recovery, robust-state fractions and consensus classifications are platform-defined outputs: cite this platform and the exact frozen protocol/analysis-plan artifact. Cite the actual validation report or archived dataset when reporting performance; no separate published validation article is asserted here. Docking scores are not measured binding affinities, and citation does not establish external validation.')
    with st.expander('Imported compounds, experimental evidence and optional ADMET/toxicity'):
        st.write('Cite each original assay publication and database record/accession used to supply a structure or label, including species, endpoint, units and access date. The platform cannot infer those sources from a SMILES string. Preserve these references in your dataset provenance.')
        st.write('ADMET, toxicity and ProLIF are not automatically produced by this live edition. For an externally generated profile, cite the exact provider/model version and its primary method paper, date, input structure and original report. A link to ProTox or another service is not evidence that a prediction was run. Do not cite a method merely because it is listed here.')
    st.markdown('[Platform source and release history](https://github.com/oavillalobos-source/P2X4/tree/streamlit-live-experimental)')
