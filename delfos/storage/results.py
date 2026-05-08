"""Tabelas de resultado em memória + persistência CSV.

Equivalente à parte de pandas do ``SB64_dash/fileshandler.py``: agrega linhas
em DataFrames e grava em CSV. A lógica numérica de ``calculate_resistivity``
e ``calculate_current_resistance`` foi portada verbatim.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from delfos.storage.paths import Paths


class ResultsStore:
    """Armazena tabelas de medidas (resistance, resistivity, sp, sev) e salva em CSV."""

    def __init__(self, paths: Paths, base_name: str):
        self.paths = paths
        self.base_name = base_name
        self.resistance: pd.DataFrame = pd.DataFrame()
        self.resistivity: pd.DataFrame = pd.DataFrame()
        self.sp: pd.DataFrame = pd.DataFrame()
        self.sev: pd.DataFrame = pd.DataFrame()

    # ------------------------------------------------------------ resistance

    def add_resistance(self, row: pd.DataFrame) -> None:
        self.resistance = _append(self.resistance, row)

    def save_resistance(self) -> None:
        self.resistance.to_csv(
            self.paths.resistance(self.base_name), sep=";", index=False
        )

    def clear_resistance(self) -> None:
        self.resistance = pd.DataFrame()

    # ----------------------------------------------------------- resistivity

    def add_resistivity(self, row: pd.DataFrame) -> None:
        self.resistivity = _append(self.resistivity, row)

    def save_resistivity(self) -> None:
        df = self.resistivity
        if not df.empty:
            df = self._calculate_current_resistance(df)
            df = self._calculate_resistivity(df)
        df.to_csv(self.paths.data(self.base_name), sep=";", index=False)

    # -------------------------------------------------------------------- sp

    def add_sp(self, row: pd.DataFrame) -> None:
        self.sp = _append(self.sp, row)

    def save_sp(self) -> None:
        self.sp.to_csv(self.paths.sp(self.base_name), sep=";", index=False)

    # ------------------------------------------------------------------- sev

    def add_sev(self, row: pd.DataFrame) -> None:
        self.sev = _append(self.sev, row)

    def save_sev(self) -> None:
        self.sev.to_csv(self.paths.sev(self.base_name), sep=";", index=False)

    # ----------------------------------------------------- arquivo Res2DInv

    def save_dat(self, *, spa: float = 2.0):
        """Gera o arquivo ``.dat`` (formato Res2DInv tipo 11) a partir da
        tabela de resistividade. Port do ``fileshandler.generate_dat`` legado.

        ``spa`` é o espaçamento entre eletrodos no header.
        """
        if self.resistivity.empty:
            raise ValueError("resistivity vazio — nada para gerar .dat")
        df = self._calculate_current_resistance(self.resistivity)
        df = self._calculate_resistivity(df)
        df = df.copy()
        df["fours"] = 4
        cols = [
            "fours", "Ax", "Ay", "Bx", "By",
            "Mx", "My", "Nx", "Ny", "resistividade",
        ]
        out = df.reindex(columns=cols)
        path = self.paths.processed(self.base_name)
        with path.open("w", encoding="utf-8") as f:
            f.write(f"{path.name}\n")
            f.write(f"{spa}\n")
            f.write("11\n")
            f.write("0\n")
            f.write("Type of measurement (0=app.resistivity 1=resistance)\n")
            f.write("0\n")
            f.write(f"{len(out)}\n")
            f.write("1\n")
            f.write("0\n")
        out.to_csv(path, sep=" ", header=False, index=False, mode="a")
        with path.open("a", encoding="utf-8") as f:
            f.write("0\n0\n0\n0\n0\n")
        return path

    # ---------------------------------------------- helpers numéricos (port)

    @staticmethod
    def _calculate_current_resistance(data_in: pd.DataFrame) -> pd.DataFrame:
        out = data_in.copy()
        out["resistencia corrente"] = round(
            1000 * out["tensao"] / out["corrente"]
        )
        return out

    @staticmethod
    def _calculate_resistivity(data_in: pd.DataFrame) -> pd.DataFrame:
        # Renomeia colunas legadas (compat com switch.py antigo).
        data_in = data_in.rename(
            columns={
                "A": "Ax", "B": "Bx", "M": "Mx", "N": "Nx",
                "vp": "Vp", "current": "corrente",
            }
        )
        for col in ("Ay", "By", "My", "Ny"):
            if col not in data_in.columns:
                data_in[col] = 0
        d1A = np.linalg.norm(
            data_in[["Mx", "My"]].values - data_in[["Ax", "Ay"]].values, axis=1
        )
        d1B = np.linalg.norm(
            data_in[["Mx", "My"]].values - data_in[["Bx", "By"]].values, axis=1
        )
        d2A = np.linalg.norm(
            data_in[["Nx", "Ny"]].values - data_in[["Ax", "Ay"]].values, axis=1
        )
        d2B = np.linalg.norm(
            data_in[["Nx", "Ny"]].values - data_in[["Bx", "By"]].values, axis=1
        )
        # evita divisão por zero — convenção do legado.
        d1A = np.where(d1A == 0, 0.01, d1A)
        d1B = np.where(d1B == 0, 0.01, d1B)
        d2A = np.where(d2A == 0, 0.01, d2A)
        d2B = np.where(d2B == 0, 0.01, d2B)
        geofactor = 2 * math.pi / (1 / d1A - 1 / d2A - 1 / d1B + 1 / d2B)
        data_in["resistividade"] = (
            (data_in["Vp"] * geofactor / data_in["corrente"]).abs().round(2)
        )
        return data_in


def _append(target: pd.DataFrame, row: pd.DataFrame) -> pd.DataFrame:
    """Concatena evitando o FutureWarning de pandas em concat com DF vazio."""
    if target.empty:
        return row.reset_index(drop=True)
    return pd.concat([target, row], ignore_index=True)
