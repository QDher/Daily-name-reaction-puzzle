const init = require('@rdkit/rdkit');
const { sameSpecies } = require('./chemkey.js');
init().then(R => {
  const cases = [
    // [label, A (drawn), B (stored), expected]; checked in both directions
    ['stereo + E/Z',            'C[C@H](O)C/C=C/C',  'CC(O)C\\C=C/C',   true],
    ['keto / enol',             'CCC(C)=O',          'CC=C(C)O',        true],
    ['enolate O- / ketone',     '[O-]C(C)=CC',       'CCC(C)=O',        true],
    ['enolate C- / ketone',     'O=C(C)[CH-]C',      'CCC(C)=O',        true],
    ['alkoxide + Li / alcohol', 'CC[O-].[Li+]',      'CCO',             true],
    ['protonated C=O / ketone', 'CC(C)=[OH+]',       'CC(C)=O',         true],
    ['ammonium / amine',        'CC[NH3+].[Cl-]',    'CCN',             true],
    ['iminium(H) / imine',      'C=[NH+]C',          'C=NC',            true],
    ['carboxylate / acid',      'CC(=O)[O-].[Na+]',  'CC(=O)O',         true],
    ['amide / imidic acid',     'CC(=O)N',           'CC(O)=N',         true],
    ['oxocarbenium forms',      'C[O+]=CC',          'CO[CH+]C',        true],
    ['nitro, two drawings',     'CC[N+](=O)[O-]',    'CCN(=O)=O',       true],
    ['carbocation / alkane',    'CC[CH+]C',          'CCCC',            false],
    ['oxocarbenium / ether',    'C[O+]=CC',          'CCOC',            false],
    ['quat. ammonium / amine',  'C[N+](C)(C)C',      'CN(C)C',          false],
    ['nitro / aci-nitro',       'CC[N+](=O)[O-]',    'CC=[N+]([O-])O',  true],
    ['dienol / enone',          'CC=CC(C)=O',        'C=CC=C(C)O',      true],
    ['b,g-enone / a,b-enone',   'C=CCC(C)=O',        'CC=CC(C)=O',      false], // net C-to-C proton move
    ['enol / other enol',       'C=C(O)CC',          'CC(O)=CC',        false], // net C-to-C proton move via the ketone
    ['two ketones, two enols',  'CC(=O)CCC(C)=O',    'C=C(O)CCC(=C)O',  true],
    ['diketone / enol-ketone',  'CC(=O)CC(C)=O',     'CC(O)=CC(C)=O',   true],
    ['allylic alcohol / enol',  'C=CCO',             'CC=CO',           false], // C-to-C
    ['phenol / cyclohexadienone','Oc1ccccc1',        'O=C1C=CCC=C1',    true],
    ['imine / enamine',         'CC(C)=NC',          'C=C(C)NC',        true],
    ['isolated alkene shift',   'C=CCCCC(C)=O',      'CC=CCCC(C)=O',    false],
    ['phenol / ketone isomer',  'Oc1ccccc1',         'O=C1CCCC=C1',     false],
    ['regioisomer',             'CCC(C)=O',          'CCCC=O',          false],
  ];
  let fail = 0;
  for (const [label, a, b, exp] of cases) {
    const ab = sameSpecies(R, a, b), ba = sameSpecies(R, b, a);
    const ok = ab === exp && ba === exp;
    if (!ok) fail++;
    console.log((ok ? 'PASS' : 'FAIL').padEnd(5), label.padEnd(26), ab && ba ? 'same' : ab || ba ? 'one-way' : 'diff');
  }
  console.log(`\n${cases.length - fail}/${cases.length} as expected`);
});
