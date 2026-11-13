"""Unit tests for mathml.py: the source convention, the refusals, and the converted output.

Run from the project folder:  python -m unittest discover -s tests -v
"""
import re
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import mathml  # noqa: E402

# Formulas taken from the actual cases (TA-2026-002, -003, -004) and the proof constructions they describe.
REAL_FORMULAS = [
    r"If every preference correspondence \(P_i\) has open graph, then the game satisfies the coalitional deviation property.",
    r"Take two players with \(X_1=X_2=\mathbb{R}\). Let \(P_2(z)=\varnothing\) and "
    r"\[P_1(z)=\left\{\,y : |y_1-z_1-2| < \frac{1}{1+|y_2|}\,\right\}.\]",
    r"Every profile \(z\) is \(\alpha\)-blocked by coalition \(\{1\}\), using \(x_1=z_1+2\).",
    r"The four-rule message mechanism implements \(F\) for every admissible integer \(1 \le k < n/2\).",
    r"Equality is permitted; any equilibrium with \(p<1/2\) would force \(p=1\), and with \(p\ge 1/2\) would force \(p=0\).",
    r"In the proof of Lemma A1, \(M(X)-M(X)\) is asserted to be a Riesz subspace of the continuous functions \(C(X)\).",
    r"\(\sum_{i=1}^n x_i \to \infty\), \(x \in \mathbb{R}^n\), \(\alpha_{\beta} \succeq 0\), \(\Pr(A)\le \varepsilon\).",
    r"\(\text{for all } x\) and \(\forall x \exists y\), \(\bar{x}\), \(\sqrt{x}\), \(\binom{n}{k}\), \(\hat{x}\), \(\%\).",
    r"\[\begin{cases} a & b \end{cases}\]",
    r"\(\boldsymbol{x}\), \(\mathbf{v}\), \(\mathcal{A}\), \(\mathrm{d}x\), \(a \, b\), \(x \le y\).",
]

MALFORMED = {
    "bare dollar": (r"costs $5", "bare '$'"),
    "unclosed": (r"\(P_i", "never closed"),
    "stray close": (r"P_i \)", "no matching opening"),
    "nested": (r"\( a \[ b \] \)", "cannot nest or mismatch"),
    "empty formula": (r"\(   \)", "empty formula"),
    "unknown command": (r"\(\foo{x}\)", "unknown command"),
    "href": (r"\(\href{http://x}{y}\)", "link, file or definition"),
    "color": (r"\(\color{red}{x}\)", "styling or markup"),
    "fbox": (r"\(\fbox{x}\)", "styling or markup"),
    "environment": (r"\(\begin{foo}x\end{foo}\)", "environment other than cases"),
    "line break": ("\\(a \\\\ b\\)", "line break"),
    "operatorname star": (r"\(\operatorname*{argmax}_x f\)", "operatorname"),
    "text injects markup": (r"\(\text{<mi>y</mi>}\)", "nests markup"),
    "ampersand in text": (r"\(\text{a&b}\)", "well-formed"),
    "unbalanced braces": (r"\(\frac{a}{b\)", "unbalanced braces"),
    "frac with one part": (r"\(\frac{a}\)", "incomplete <mfrac>"),
    "binomial with one argument": (r"\(\binom{n}\)", "incomplete <mfrac>"),
    "empty accent group": (r"\(\hat{}\)", "empty group"),
    "empty superscript": (r"\(x^{}\)", "empty group"),
    "unescaped percent": (r"\(a % c\)", "unescaped %"),
    "control character": ("\\(x\x0c\\)", "control character"),
    "delimiter in plain field": (r"plain \(x\)", None),
    "double script": (r"\(x__y\)", "two scripts in a row"),
    "script at the start": (r"\(^2\)", "nothing to attach"),
    "script after an operator": (r"\(a=^2\)", "nothing to attach"),
    "script after an open bracket": (r"\((^2)\)", "nothing to attach"),
    "empty script base": (r"\(x^{_}\)", "nothing to attach"),
    "empty optional argument": (r"\(\sqrt[]{x}\)", "empty optional argument"),
    "spacing-only group": (r"\(\frac{\,}{b}\)", "empty group"),
    "multi-row cases": ("\\(\\begin{cases} a \\\\ b \\end{cases}\\)", "line break"),
}


class MathTests(unittest.TestCase):
    def test_real_formulas_convert_and_keep_their_tex(self):
        for text in REAL_FORMULAS:
            out = mathml.render(text, "test", math=True)
            self.assertIn("<math", out)
            self.assertNotIn("\\(", out)
            self.assertNotIn("\\[", out)
            annotations = re.findall(r'<annotation encoding="application/x-tex">(.*?)</annotation>', out)
            self.assertTrue(annotations)
            for ann in annotations:
                self.assertNotIn("<", ann)  # escaped, so the TeX cannot inject markup

    def test_output_uses_only_allowed_elements_and_no_merror(self):
        for text in REAL_FORMULAS:
            out = mathml.render(text, "test", math=True)
            maths = "".join(re.findall(r"<math.*?</math>", out, re.S))  # the span wrapper is not MathML
            tags = set(re.findall(r"<([a-z]+)[ >/]", maths))
            self.assertLessEqual(tags, mathml.ALLOWED_TAGS | {"semantics", "annotation"}, text)
            self.assertNotIn("merror", out)
            self.assertNotIn("href", out)
            self.assertNotIn("style=", out)

    def test_malformed_and_unsafe_input_is_refused_with_the_record_named(self):
        for name, (text, reason) in MALFORMED.items():
            if reason is None:
                with self.assertRaises(mathml.MathError, msg=name):
                    mathml.render(text, "record TEST-X field f", math=False)
                continue
            with self.assertRaises(mathml.MathError, msg=name) as ctx:
                mathml.render(text, "record TEST-X field f", math=True)
            self.assertIn("record TEST-X field f", str(ctx.exception), name)
            self.assertIn(reason, str(ctx.exception), name)

    def test_plain_fields_refuse_any_delimiter(self):
        with self.assertRaises(mathml.MathError):
            mathml.render("title \\(x\\)", "title", math=False)
        self.assertEqual(mathml.render("A & B", "title", math=False), "A &amp; B")

    def test_display_math_is_a_span_so_it_may_sit_in_a_paragraph(self):
        out = mathml.render("Then \\[x=1\\] holds.", "t")
        self.assertIn('<span class="math-display" tabindex="0"><math display="block">', out)
        self.assertNotIn("<div", out)

    def test_plain_search_text_removes_delimiters(self):
        self.assertEqual(mathml.plain("a \\(P_i\\) b").split(), ["a", "P_i", "b"])


if __name__ == "__main__":
    unittest.main()
