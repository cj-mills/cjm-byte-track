# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/00_byte_tracker.ipynb.

# %% auto 0
__all__ = ['BYTETracker', 'joint_stracks', 'sub_stracks', 'remove_duplicate_stracks']

# %% ../nbs/00_byte_tracker.ipynb 3
import numpy as np
from .strack import STrack
from .kalman_filter import KalmanFilter
from .matching import iou_distance, linear_assignment
from .basetrack import BaseTrack, TrackState

# %% ../nbs/00_byte_tracker.ipynb 5
class BYTETracker:
    """
    BYTETracker is a class for tracking objects in video streams using bounding box detections, with methods for processing and updating tracks based on detection results and IoU matching.
    """
    def __init__(self, 
                 track_thresh:float=0.25, # Threshold value for tracking.
                 track_buffer:int=30, # Size of buffer for tracking.
                 match_thresh:float=0.8, # Threshold value for matching tracks to detections.
                 frame_rate:int=30 # Frame rate of the input video stream.
                ):
        """
        Initializes the BYTETracker.
        """

        # Thresholds for tracking and matching
        self.track_thresh = track_thresh
        self.match_thresh = match_thresh
        
        # Frame count
        self.frame_id = 0
        
        # Detection threshold, calculated based on the given track_thresh
        self.det_thresh = track_thresh + 0.1
        
        # Calculate buffer size based on given frame rate and track buffer
        self.buffer_size = int(frame_rate / 30.0 * track_buffer)
        
        # Maximum time a track is considered lost
        self.max_time_lost = self.buffer_size
        
        # Initialize Kalman filter
        self.kalman_filter = KalmanFilter()
        
        # Lists to store different kinds of tracks
        self.tracked_stracks = []
        self.lost_stracks = []
        self.removed_stracks = []
        
        BaseTrack._count = 0

    def _process_output(self, 
                        output_results # Detection results.
                       ) -> tuple: # scores and bounding boxes.
        """
        Process the output results to separate scores and bounding boxes.
        """

        # Check if output has 5 columns (indicating it contains scores only)
        if output_results.shape[1] == 5:
            scores = output_results[:, 4]
        else:
            output_results = output_results.cpu().numpy()
            # Calculate scores if output has more columns
            scores = output_results[:, 4] * output_results[:, 5]
        
        # Extract bounding boxes
        bboxes = output_results[:, :4]
        return scores, bboxes

    def _scale_bboxes(self, 
                      img_info:tuple, # Original height and width of the image.
                      img_size:tuple, # Target size.
                      bboxes:list # List of bounding boxes.
                     ) -> list: # Scaled bounding boxes.
        """
        Scale bounding boxes based on image size.
        """

        img_h, img_w = img_info
        scale = min(img_size[0] / float(img_h), img_size[1] / float(img_w))
        return bboxes / scale

    def _get_detections(self, 
                        dets:list, # List of detections.
                        scores_keep:list # Scores for the detections.
                       ) -> list: # List of STrack objects.
        """
        Convert bounding boxes to STrack objects.
        """

        return [STrack(STrack.tlbr_to_tlwh(tlbr), s) for tlbr, s in zip(dets, scores_keep)] if dets.size > 0 else []

    def _update_tracked_stracks(self
                               ) -> tuple: # List of unconfirmed and tracked tracks.
        """
        Update the list of tracked and unconfirmed tracks.
        """

        unconfirmed = [track for track in self.tracked_stracks if not track.is_activated]
        tracked_stracks = [track for track in self.tracked_stracks if track.is_activated]
        return unconfirmed, tracked_stracks

    def _match_tracks_to_detections(self, 
                                    stracks:list, # List of tracks.
                                    detections:list, # List of detections.
                                    thresh:float # IOU threshold for matching.
                                   ) -> tuple: # Matches and unmatched tracks and detections.
        """
        Match tracks to detections using IOU.
        """

        dists = iou_distance(stracks, detections)
        return linear_assignment(dists, thresh=thresh)

    def _update_tracks(self, 
                       stracks:list, # List of tracks.
                       detections:list, # List of detections.
                       matches:list, # Matched track-detection pairs.
                       refind_stracks:list, # List to add refind tracks.
                       activated_stracks:list # List to add activated tracks.
                      ):
        """
        Update tracks based on matches with detections.
        """

        for itracked, idet in matches:
            track = stracks[itracked]
            det = detections[idet]
            if track.state == TrackState.Tracked:
                track.update(det, self.frame_id)
                activated_stracks.append(track)
            else:
                track.re_activate(det, self.frame_id, new_id=False)
                refind_stracks.append(track)

    def update(self, 
               output_results, # Detection results.
               img_info:tuple, # Original height and width of the image.
               img_size:tuple # Target size.
              ) -> list: # List of activated tracks.
        """
        Update the tracker based on new detections.
        """

        self.frame_id += 1
        refind_stracks, activated_stracks, lost_stracks, removed_stracks = [], [], [], []

        scores, bboxes = self._process_output(output_results)
        bboxes = self._scale_bboxes(img_info, img_size, bboxes)
        detections = self._get_detections(bboxes[scores > self.track_thresh], scores[scores > self.track_thresh])
        detections_second = self._get_detections(bboxes[np.logical_and(scores > 0.1, scores < self.track_thresh)], 
                                                 scores[np.logical_and(scores > 0.1, scores < self.track_thresh)])

        # Update tracked stracks
        unconfirmed, tracked_stracks = self._update_tracked_stracks()
        strack_pool = joint_stracks(tracked_stracks, self.lost_stracks)
        STrack.multi_predict(strack_pool)

        # Match and update tracks
        matches, u_track, u_detection = self._match_tracks_to_detections(strack_pool, detections, self.match_thresh)
        self._update_tracks(strack_pool, detections, matches, refind_stracks, activated_stracks)

        # Additional matching and track updates
        r_tracked_stracks = [strack_pool[i] for i in u_track if strack_pool[i].state == TrackState.Tracked]
        matches, u_track, _ = self._match_tracks_to_detections(r_tracked_stracks, detections_second, thresh=0.5)
        self._update_tracks(r_tracked_stracks, detections_second, matches, refind_stracks, activated_stracks)
        for it in u_track:
            track = r_tracked_stracks[it]
            if not track.state == TrackState.Lost:
                track.mark_lost()
                lost_stracks.append(track)

        # Update unconfirmed tracks
        detections = [detections[i] for i in u_detection]
        matches, u_unconfirmed, u_detection = self._match_tracks_to_detections(unconfirmed, detections, thresh=0.7)
        for itracked, idet in matches:
            unconfirmed[itracked].update(detections[idet], self.frame_id)
            activated_stracks.append(unconfirmed[itracked])
        for it in u_unconfirmed:
            track = unconfirmed[it]
            track.mark_removed()
            removed_stracks.append(track)

        # Handle new tracks
        for inew in u_detection:
            track = detections[inew]
            if track.score >= self.det_thresh:
                track.activate(self.kalman_filter, self.frame_id)
                activated_stracks.append(track)

        # Handle lost and removed tracks
        for track in self.lost_stracks:
            if self.frame_id - track.end_frame > self.max_time_lost:
                track.mark_removed()
                removed_stracks.append(track)

        removed_stracks.extend([track for track in self.lost_stracks if self.frame_id - track.end_frame > self.max_time_lost])
        self.tracked_stracks = [t for t in self.tracked_stracks if t.state == TrackState.Tracked]
        self.tracked_stracks = joint_stracks(self.tracked_stracks, activated_stracks)
        self.tracked_stracks = joint_stracks(self.tracked_stracks, refind_stracks)
        self.lost_stracks = sub_stracks(self.lost_stracks, self.tracked_stracks)
        self.lost_stracks.extend(lost_stracks)
        self.lost_stracks = sub_stracks(self.lost_stracks, self.removed_stracks)
        self.removed_stracks.extend(removed_stracks)
        self.tracked_stracks, self.lost_stracks = remove_duplicate_stracks(self.tracked_stracks, self.lost_stracks)
        return [track for track in self.tracked_stracks if track.is_activated]

# %% ../nbs/00_byte_tracker.ipynb 15
def joint_stracks(track_list_a:list, # The first list of tracks.
                  track_list_b:list # The second list of tracks.
                 ) -> list: # A combined list of unique tracks.
    """
    Combines two lists of tracks ensuring each track is unique based on its track_id.
    """
    # Using a dictionary comprehension to ensure unique tracks based on track_id
    unique_tracks = {track.track_id: track for track in track_list_a + track_list_b}
    
    return list(unique_tracks.values())

# %% ../nbs/00_byte_tracker.ipynb 16
def sub_stracks(track_list_a:list, # The list of tracks to subtract from.
                track_list_b:list # The list of tracks to subtract.
               ) -> list: # A list containing tracks from track_list_a that are not in track_list_b.
    """
    Subtracts the tracks in track_list_b from track_list_a based on track_id.
    """
    # Creating a set of track_ids from track_list_b for efficient look-up
    track_ids_b = {track.track_id for track in track_list_b}
    
    # Return tracks from track_list_a that are not in track_list_b based on track_id
    return [track for track in track_list_a if track.track_id not in track_ids_b]

# %% ../nbs/00_byte_tracker.ipynb 17
def remove_duplicate_stracks(s_tracks_a:list, # The first list of tracks.
                             s_tracks_b:list # The second list of tracks.
                            ) -> tuple: # Two lists of tracks with duplicates removed.
    """
    Removes duplicate tracks from two lists based on a defined distance metric and time criteria. 
    """
    # Calculate pairwise distance between tracks in the two lists
    pairwise_distance = iou_distance(s_tracks_a, s_tracks_b)
    
    # Identify pairs of tracks with distance less than 0.15 (indicating potential duplicates)
    pairs = np.where(pairwise_distance < 0.15)

    # Sets to store indexes of duplicate tracks in each list
    duplicates_a, duplicates_b = set(), set()
    
    for track_a_index, track_b_index in zip(*pairs):
        # Calculate how long each track has been in the list
        time_a = s_tracks_a[track_a_index].frame_id - s_tracks_a[track_a_index].start_frame
        time_b = s_tracks_b[track_b_index].frame_id - s_tracks_b[track_b_index].start_frame
        
        # Compare times and add the newer track to the duplicate set
        if time_a > time_b:
            duplicates_b.add(track_b_index)
        else:
            duplicates_a.add(track_a_index)

    # Filter out duplicates from the original lists
    result_a = [track for i, track in enumerate(s_tracks_a) if i not in duplicates_a]
    result_b = [track for i, track in enumerate(s_tracks_b) if i not in duplicates_b]
    
    return result_a, result_b

