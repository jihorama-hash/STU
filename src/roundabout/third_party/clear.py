# Upstream source: TrackEval/trackeval/metrics/clear.py
# Upstream commit: 12c8791b303e0a0b50f753af204249e622d0281a
# Minimal integration changes: retained CLEAR sequence scoring and final-field
# calculation; removed TrackEval configuration, timing, reporting, and sequence
# aggregation helpers. The caller supplies the approved IoU threshold.
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


class CLEAR:
    """TrackEval CLEAR sequence metrics used by the R01 evaluator."""

    def __init__(self, config=None):
        self.threshold = float((config or {}).get("THRESHOLD", 0.5))

    def eval_sequence(self, data):
        res = {field: 0 for field in (
            "CLR_TP", "CLR_FN", "CLR_FP", "IDSW", "MOTA", "MOTP_sum",
            "MOTP", "CLR_Re", "CLR_Pr", "MODA", "CLR_Frames",
        )}
        if data["num_tracker_dets"] == 0:
            res["CLR_FN"] = data["num_gt_dets"]
            res["matches_by_timestep"] = [([], []) for _ in data["gt_ids"]]
            return res
        if data["num_gt_dets"] == 0:
            res["CLR_FP"] = data["num_tracker_dets"]
            res["matches_by_timestep"] = [([], []) for _ in data["gt_ids"]]
            return res

        num_gt_ids = data["num_gt_ids"]
        gt_id_count = np.zeros(num_gt_ids)
        prev_tracker_id = np.nan * np.zeros(num_gt_ids)
        prev_timestep_tracker_id = np.nan * np.zeros(num_gt_ids)
        matches_by_timestep = []
        for gt_ids_t, tracker_ids_t, similarity in zip(
            data["gt_ids"], data["tracker_ids"], data["similarity_scores"]
        ):
            if len(gt_ids_t) == 0:
                res["CLR_FP"] += len(tracker_ids_t)
                matches_by_timestep.append(([], []))
                continue
            if len(tracker_ids_t) == 0:
                res["CLR_FN"] += len(gt_ids_t)
                gt_id_count[gt_ids_t] += 1
                matches_by_timestep.append(([], []))
                continue

            score_mat = tracker_ids_t[np.newaxis, :] == prev_timestep_tracker_id[
                gt_ids_t[:, np.newaxis]
            ]
            score_mat = 1000 * score_mat + similarity
            score_mat[similarity < self.threshold - np.finfo("float").eps] = 0
            match_rows, match_cols = linear_sum_assignment(-score_mat)
            actually_matched = score_mat[match_rows, match_cols] > np.finfo("float").eps
            match_rows, match_cols = match_rows[actually_matched], match_cols[actually_matched]
            matches_by_timestep.append((match_rows.tolist(), match_cols.tolist()))
            matched_gt_ids = gt_ids_t[match_rows]
            matched_tracker_ids = tracker_ids_t[match_cols]
            previous_ids = prev_tracker_id[matched_gt_ids]
            res["IDSW"] += np.sum(
                np.logical_not(np.isnan(previous_ids))
                & np.not_equal(matched_tracker_ids, previous_ids)
            )
            gt_id_count[gt_ids_t] += 1
            prev_tracker_id[matched_gt_ids] = matched_tracker_ids
            prev_timestep_tracker_id[:] = np.nan
            prev_timestep_tracker_id[matched_gt_ids] = matched_tracker_ids
            num_matches = len(matched_gt_ids)
            res["CLR_TP"] += num_matches
            res["CLR_FN"] += len(gt_ids_t) - num_matches
            res["CLR_FP"] += len(tracker_ids_t) - num_matches
            if num_matches:
                res["MOTP_sum"] += sum(similarity[match_rows, match_cols])

        res["CLR_Frames"] = data["num_timesteps"]
        res["matches_by_timestep"] = matches_by_timestep
        gt_dets = res["CLR_TP"] + res["CLR_FN"]
        res["MOTA"] = (res["CLR_TP"] - res["CLR_FP"] - res["IDSW"]) / max(1.0, gt_dets)
        res["MOTP"] = res["MOTP_sum"] / max(1.0, res["CLR_TP"])
        res["CLR_Re"] = res["CLR_TP"] / max(1.0, gt_dets)
        res["CLR_Pr"] = res["CLR_TP"] / max(1.0, res["CLR_TP"] + res["CLR_FP"])
        res["MODA"] = (res["CLR_TP"] - res["CLR_FP"]) / max(1.0, gt_dets)
        return res
