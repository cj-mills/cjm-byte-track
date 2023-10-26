# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/04_matching.ipynb.

# %% auto 0
__all__ = ['box_iou_batch', 'indices_to_matches', 'linear_assignment', 'ious', 'iou_distance', 'match_detections_with_tracks']

# %% ../nbs/04_matching.ipynb 3
from typing import List
import numpy as np
from scipy.optimize import linear_sum_assignment

from .strack import STrack

# %% ../nbs/04_matching.ipynb 4
def box_iou_batch(boxes_true:np.ndarray, # Ground truth bounding boxes, shape (N, 4) format (x_min, y_min, x_max, y_max).
                  boxes_detection:np.ndarray # Detected bounding boxes, shape (M, 4), format (x_min, y_min, x_max, y_max).
                 ) -> np.ndarray: # IoU matrix of shape (N, M) where each element (i, j) represents the IoU between boxes_true[i] and boxes_detection[j].
    """
    Compute the Intersection over Union (IoU) between two sets of bounding boxes.
    """
    # Compute areas of the true boxes and detected boxes
    area_true = (boxes_true[:, 2] - boxes_true[:, 0]) * (boxes_true[:, 3] - boxes_true[:, 1])
    area_detection = (boxes_detection[:, 2] - boxes_detection[:, 0]) * (boxes_detection[:, 3] - boxes_detection[:, 1])

    # Find the top left and bottom right coordinates for the intersections
    top_left = np.maximum(boxes_true[:, None, :2], boxes_detection[:, :2])
    bottom_right = np.minimum(boxes_true[:, None, 2:], boxes_detection[:, 2:])

    # Compute intersection areas
    area_inter = np.prod(np.maximum(bottom_right - top_left, 0), axis=2)

    # Compute IoU values for each pair of boxes
    return area_inter / (area_true[:, None] + area_detection - area_inter)

# %% ../nbs/04_matching.ipynb 5
def indices_to_matches(cost_matrix:np.ndarray, # The matrix of costs.
                        indices:tuple, # Indices of potential matches.
                        thresh:float # Threshold for valid matches.
                       ) -> tuple: # Contains three elements: Matched indices., Unmatched indices from the first set. Unmatched indices from the second set.
    """
    Extract matched and unmatched indices based on a threshold.
    """
    indices_array = np.array(indices)
    matched_mask = cost_matrix[tuple(indices_array.T)] <= thresh

    matches = indices_array[matched_mask]
    unmatched_a = tuple(np.setdiff1d(np.arange(cost_matrix.shape[0]), matches[:, 0]))
    unmatched_b = tuple(np.setdiff1d(np.arange(cost_matrix.shape[1]), matches[:, 1]))

    return matches, unmatched_a, unmatched_b

# %% ../nbs/04_matching.ipynb 6
def linear_assignment(cost_matrix:np.ndarray, # The matrix of costs.
                      thresh:float # Threshold for valid matches.
                     ) -> tuple: # Contains three elements: Matched indices, Unmatched indices from the first set., Unmatched indices from the second set.
    """
    Perform linear assignment to minimize the total cost.
    """
    if not cost_matrix.size:
        return (np.empty((0, 2), dtype=int), 
                tuple(range(cost_matrix.shape[0])), 
                tuple(range(cost_matrix.shape[1])))
    
    # Replace values above threshold with a high value
    cost_matrix = np.where(cost_matrix > thresh, thresh + 1e-4, cost_matrix)
    row_ind, col_ind = linear_sum_assignment(cost_matrix)
    
    return indices_to_matches(cost_matrix, np.column_stack((row_ind, col_ind)), thresh)

# %% ../nbs/04_matching.ipynb 7
def ious(atlbrs, # List of bounding boxes from the first set. 
         btlbrs # List of bounding boxes from the second set.
        ) -> np.ndarray: # IoU matrix.
    """
    Compute the IoU between two sets of bounding boxes.
    """
    if not atlbrs or not btlbrs:
        return np.zeros((len(atlbrs), len(btlbrs)), dtype=float)

    return box_iou_batch(
        np.ascontiguousarray(atlbrs, dtype=float),
        np.ascontiguousarray(btlbrs, dtype=float)
    )

# %% ../nbs/04_matching.ipynb 8
def iou_distance(
    atracks:list, # List of tracks from the first set. Each track can be an ndarray or an object with a 'tlbr' attribute.
    btracks:list # List of tracks from the second set. Each track can be an ndarray or an object with a 'tlbr' attribute.
) -> np.ndarray: # Cost matrix where each element (i, j) represents the cost of associating atracks[i] with btracks[j].
    """
    Compute the cost matrix based on IoU for two sets of tracks.
    """
    # Determine if tracks should be directly used or if 'tlbr' attribute should be extracted
    should_extract_tlbr = len(atracks) > 0 and not isinstance(atracks[0], np.ndarray)

    # Extract 'tlbr' attribute if required
    atlbrs = [track.tlbr for track in atracks] if should_extract_tlbr else atracks
    btlbrs = [track.tlbr for track in btracks] if should_extract_tlbr else btracks

    # Compute IoU and derive the cost matrix
    _ious = ious(atlbrs, btlbrs)
    cost_matrix = 1 - _ious

    return cost_matrix

# %% ../nbs/04_matching.ipynb 9
def match_detections_with_tracks(tlbr_boxes: np.ndarray, # An array of detected bounding boxes, represented as [top, left, bottom, right].
                                 track_ids: np.ndarray, # An array of track IDs corresponding to the input bounding boxes.
                                 tracks: List[STrack] # A list of track objects representing the current tracked objects.
                                ) -> np.ndarray: # An array of updated track IDs where the detections are matched with the existing tracks.

    """
    Match detected bounding boxes with existing tracks using Intersection Over Union (IOU).

    Note:
    - If a detected bounding box does not match any existing track (i.e., IOU is zero), its corresponding track ID remains unchanged.
    """
    
    # Calculate IOU
    tracks_boxes = np.array([track.tlbr for track in tracks])
    iou = box_iou_batch(tracks_boxes, tlbr_boxes)
    
    # Get indices with maximum IOU values
    track2detection = np.argmax(iou, axis=1)
    max_iou_values = np.max(iou, axis=1)
    
    # Update track_ids where IOU is not zero
    valid_indices = max_iou_values != 0
    valid_track_indices = np.arange(len(tracks))[valid_indices]
    for idx in valid_track_indices:
        track_ids[track2detection[idx]] = tracks[idx].track_id
    
    return track_ids
