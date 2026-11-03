# Upstream source: TrackEval/trackeval/metrics/identity.py
# Upstream commit: 12c8791b303e0a0b50f753af204249e622d0281a
# Minimal integration changes: retained Identity sequence scoring; removed
# TrackEval configuration, timing, reporting, and aggregation helpers. Replaced
# deprecated np.int casts with Python int and accept the threshold from caller.
#
# MIT License
# Copyright (c) 2020 Jonathon Luiten
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import numpy as np
from scipy.optimize import linear_sum_assignment


class Identity:
    """TrackEval Identity sequence metrics used by the R01 evaluator."""

    def __init__(self, config=None):
        self.threshold = float((config or {}).get("THRESHOLD", 0.5))

    def eval_sequence(self, data):
        res = {"IDTP": 0, "IDFN": 0, "IDFP": 0, "IDF1": 0.0, "IDR": 0.0, "IDP": 0.0}
        if data["num_tracker_dets"] == 0:
            res["IDFN"] = data["num_gt_dets"]
            return res
        if data["num_gt_dets"] == 0:
            res["IDFP"] = data["num_tracker_dets"]
            return res

        num_gt_ids, num_tracker_ids = data["num_gt_ids"], data["num_tracker_ids"]
        potential = np.zeros((num_gt_ids, num_tracker_ids))
        gt_count = np.zeros(num_gt_ids)
        tracker_count = np.zeros(num_tracker_ids)
        for gt_ids_t, tracker_ids_t, similarity in zip(
            data["gt_ids"], data["tracker_ids"], data["similarity_scores"]
        ):
            matches = similarity >= self.threshold
            match_gt, match_tracker = np.nonzero(matches)
            potential[gt_ids_t[match_gt], tracker_ids_t[match_tracker]] += 1
            gt_count[gt_ids_t] += 1
            tracker_count[tracker_ids_t] += 1

        fp_mat = np.zeros((num_gt_ids + num_tracker_ids, num_gt_ids + num_tracker_ids))
        fn_mat = np.zeros_like(fp_mat)
        fp_mat[num_gt_ids:, :num_tracker_ids] = 1e10
        fn_mat[:num_gt_ids, num_tracker_ids:] = 1e10
        for gt_id in range(num_gt_ids):
            fn_mat[gt_id, :num_tracker_ids] = gt_count[gt_id]
            fn_mat[gt_id, num_tracker_ids + gt_id] = gt_count[gt_id]
        for tracker_id in range(num_tracker_ids):
            fp_mat[:num_gt_ids, tracker_id] = tracker_count[tracker_id]
            fp_mat[tracker_id + num_gt_ids, tracker_id] = tracker_count[tracker_id]
        fn_mat[:num_gt_ids, :num_tracker_ids] -= potential
        fp_mat[:num_gt_ids, :num_tracker_ids] -= potential
        rows, cols = linear_sum_assignment(fn_mat + fp_mat)
        res["IDFN"] = int(fn_mat[rows, cols].sum())
        res["IDFP"] = int(fp_mat[rows, cols].sum())
        res["IDTP"] = int(gt_count.sum() - res["IDFN"])
        res["IDR"] = res["IDTP"] / max(1.0, res["IDTP"] + res["IDFN"])
        res["IDP"] = res["IDTP"] / max(1.0, res["IDTP"] + res["IDFP"])
        res["IDF1"] = res["IDTP"] / max(
            1.0, res["IDTP"] + 0.5 * res["IDFP"] + 0.5 * res["IDFN"]
        )
        return res
