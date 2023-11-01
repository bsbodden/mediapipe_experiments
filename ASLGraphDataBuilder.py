import os
import json
import numpy as np
import pandas as pd
from tqdm import tqdm
from scipy.signal import savgol_filter
from dotenv import load_dotenv


class ASLGraphDataBuilder:
    def __init__(self, base_dir, signs_to_process, max_files_per_sign, target_frames):
        """
        Initializes the ASLGraphDataBuilder class.

        :param base_dir: The base directory where the dataset is stored.
        :param signs_to_process: A list of signs that should be processed. If None, all signs will be processed.
        :param max_files_per_sign: The maximum number of files to process for each sign.
        :param target_frames: The target number of frames to interpolate to for each example.
        """
        self.base_dir = base_dir
        self.signs_to_process = signs_to_process
        self.max_files_per_sign = max_files_per_sign
        self.target_frames = target_frames

        # Load the train dataframe and label map
        self.train_df = pd.read_csv(os.path.join(self.base_dir, "train.csv"))

        if not signs_to_process:
            self.signs_to_process = self.train_df["sign"].unique().tolist()
        else:
            self.signs_to_process = signs_to_process

        with open(
            os.path.join(self.base_dir, "sign_to_prediction_index_map.json")
        ) as f:
            self.label_map = json.load(f)

    def _filter_files_by_sign(self, sign):
        """
        Filters and returns the file paths for a given sign.

        :param sign: The sign to filter files for.
        :return: A list of file paths for the given sign.
        """
        sign_files = self.train_df[self.train_df["sign"] == sign]["path"].tolist()[
            : self.max_files_per_sign
        ]
        return [os.path.join(self.base_dir, f) for f in sign_files]

    def _remove_empty_frames(self, df):
        """
        Removes frames from the dataframe where all landmarks are missing.

        :param df: The dataframe to remove empty frames from.
        :return: The dataframe with empty frames removed.
        """
        df = df.groupby("frame").filter(
            lambda group: group[["x", "y"]].notna().any().any()
        )
        return df

    def _extract_relevant_landmarks(self, df):
        """
        Filters the dataframe to only include relevant landmarks.

        :param df: The dataframe to filter.
        :return: The dataframe with only relevant landmarks.
        """
        relevant_landmarks = [
            *[
                "pose-" + str(i)
                for i in [
                    0,
                    1,
                    2,
                    3,
                    4,
                    5,
                    6,
                    9,
                    10,
                    11,
                    12,
                    13,
                    14,
                    15,
                    16,
                    23,
                    24,
                    25,
                    26,
                    27,
                    28,
                ]
            ],
            *[
                "face-" + str(i)
                for i in [
                    33,
                    34,
                    35,
                    36,
                    37,
                    38,
                    39,
                    40,
                    41,
                    42,
                    43,
                    44,
                    45,
                    46,
                    61,
                    62,
                    63,
                    64,
                    66,
                    291,
                    292,
                    293,
                    294,
                    295,
                    296,
                ]
            ],
            *["right_hand-" + str(i) for i in range(21)],
            *["left_hand-" + str(i) for i in range(21)],
        ]

        df["landmark_type"] = df["row_id"].apply(lambda x: x.split("-")[1])
        df["landmark_index"] = df["row_id"].apply(lambda x: int(x.split("-")[2]))
        df["landmark_id"] = df["landmark_type"] + "-" + df["landmark_index"].astype(str)
        df_filtered = df[df["landmark_id"].isin(relevant_landmarks)]
        df_filtered = df_filtered[
            ["row_id", "landmark_index", "x", "y", "frame", "type"]
        ]
        return df_filtered

    def _handle_nan_values(self, df):
        """
        Handles NaN values in the dataframe by interpolating missing values and then dropping any remaining NaN values.

        :param df: The dataframe to handle NaN values in.
        :return: The dataframe with NaN values handled.
        """
        df = self._interpolate_landmarks(df)
        df.dropna(subset=["x", "y"], inplace=True)
        return df

    def _interpolate_landmarks(self, df):
        """
        Interpolates missing values for each landmark type in the dataframe.

        :param df: The dataframe to interpolate values in.
        :return: The dataframe with interpolated values.
        """
        for landmark_type in df["type"].unique():
            mask = df["type"] == landmark_type

            df.loc[mask, "x"] = df.loc[mask, "x"].interpolate(
                method="linear", limit_direction="both"
            )
            df.loc[mask, "y"] = df.loc[mask, "y"].interpolate(
                method="linear", limit_direction="both"
            )

            mean_x = df.loc[mask, "x"].mean()
            mean_y = df.loc[mask, "y"].mean()
            df.loc[mask, "x"] = df.loc[mask, "x"].fillna(mean_x)
            df.loc[mask, "y"] = df.loc[mask, "y"].fillna(mean_y)

        return df

    def _drop_z_coordinate(self, df):
        """
        Drops the z-coordinate from the dataframe if it exists.

        :param df: The dataframe to drop the z-coordinate from.
        :return: The dataframe without the z-coordinate.
        """
        return df.drop(columns=["z"], errors="ignore")

    def _normalize_coordinates(self, df):
        """
        Normalizes the x and y coordinates in the dataframe by subtracting the centroid.

        :param df: The dataframe to normalize coordinates in.
        :return: The dataframe with normalized coordinates.
        """
        centroid = df[["x", "y"]].mean().tolist()
        df["x"] = df["x"] - centroid[0]
        df["y"] = df["y"] - centroid[1]
        return df

    def _smooth_landmarks(self, df, window_length, polyorder):
        """
        Applies a Savitzky-Golay filter to smooth the landmark coordinates in the dataframe.

        :param df: The dataframe to smooth landmarks in.
        :param window_length: The length of the filter window.
        :param polyorder: The order of the polynomial used to fit the samples.
        :return: The dataframe with smoothed landmarks.
        """
        if window_length % 2 == 0 or window_length <= polyorder:
            raise ValueError("window_length must be an odd number and >= polyorder.")

        for landmark_type in df["type"].unique():
            mask = df["type"] == landmark_type

            if window_length > mask.sum():
                raise ValueError(
                    "window_length is too large for the number of frames. Reduce window_length or use more frames."
                )

            df.loc[mask, "x"] = savgol_filter(
                df.loc[mask, "x"], window_length, polyorder
            )
            df.loc[mask, "y"] = savgol_filter(
                df.loc[mask, "y"], window_length, polyorder
            )

        return df

    def _interpolate_frames(self, df):
        """
        Interpolates or reduces the number of frames in the dataframe to match the target number of frames.

        :param df: The dataframe to interpolate or reduce frames in.
        :return: The dataframe with interpolated or reduced frames.
        """
        num_frames = len(df["frame"].unique())
        df["frame"] = df["frame"].rank(method="dense").astype(int) - 1
        df.sort_values(by=["frame", "landmark_index"], inplace=True)

        if num_frames < self.target_frames:
            return self._increase_frames(df)
        elif num_frames > self.target_frames:
            return self._reduce_frames(df)

        return df

    def _increase_frames(self, df):
        """
        Increases the number of frames in the dataframe to match the target number of frames.

        :param df: The dataframe to increase frames in.
        :return: The dataframe with increased frames.
        """
        num_frames = df["frame"].nunique()
        num_landmarks = df["landmark_index"].nunique()
        target_frames = np.linspace(0, num_frames - 1, self.target_frames)
        lower_frames = np.floor(target_frames).astype(int)
        upper_frames = np.ceil(target_frames).astype(int)
        alphas = target_frames - lower_frames

        interpolated_x = []
        interpolated_y = []
        landmark_indices = []
        types = []
        frames = []

        for i in range(self.target_frames):
            lower_frame = int(lower_frames[i])
            upper_frame = int(upper_frames[i])
            alpha = alphas[i]

            for landmark_index in range(num_landmarks):
                lower_frame_data = df[
                    (df["frame"] == lower_frame)
                    & (df["landmark_index"] == landmark_index)
                ]
                upper_frame_data = df[
                    (df["frame"] == upper_frame)
                    & (df["landmark_index"] == landmark_index)
                ]

                if lower_frame_data.empty or upper_frame_data.empty:
                    continue

                interpolated_x.append(
                    (1 - alpha) * lower_frame_data["x"].values[0]
                    + alpha * upper_frame_data["x"].values[0]
                )
                interpolated_y.append(
                    (1 - alpha) * lower_frame_data["y"].values[0]
                    + alpha * upper_frame_data["y"].values[0]
                )
                landmark_indices.append(landmark_index)
                types.append(lower_frame_data["type"].values[0])
                frames.append(i)

        new_df = pd.DataFrame(
            {
                "frame": frames,
                "landmark_index": landmark_indices,
                "x": interpolated_x,
                "y": interpolated_y,
                "type": types,
            }
        )

        return new_df

    def _reduce_frames(self, df):
        """
        Reduces the number of frames in the dataframe to match the target number of frames.

        :param df: The dataframe to reduce frames in.
        :return: The dataframe with reduced frames.
        """
        num_frames = len(df["frame"].unique())
        frames_to_keep = np.linspace(0, num_frames - 1, self.target_frames, dtype=int)
        df = df[df["frame"].isin(frames_to_keep)].copy()
        df["frame"] = df["frame"].rank(method="dense").astype(int) - 1
        return df

    def _calculate_hand_features(self, df):
        """
        Calculates hand features for each frame in the dataframe.

        :param df: The dataframe to calculate hand features in.
        :return: The dataframe with hand features calculated.
        """
        # Initialize hand feature columns with NaN
        for hand in ["right_hand", "left_hand"]:
            df[f"{hand}_thumb_index_distance"] = np.nan
            df[f"{hand}_palm_orientation"] = np.nan

        for frame_number in df["frame"].unique():
            frame_data = df[df["frame"] == frame_number]
            for hand in ["right_hand", "left_hand"]:
                # Extract relevant landmarks
                wrist = frame_data[
                    (frame_data["type"] == hand) & (frame_data["landmark_index"] == 0)
                ][["x", "y"]].values
                thumb_tip = frame_data[
                    (frame_data["type"] == hand) & (frame_data["landmark_index"] == 4)
                ][["x", "y"]].values
                index_tip = frame_data[
                    (frame_data["type"] == hand) & (frame_data["landmark_index"] == 8)
                ][["x", "y"]].values
                pinky_tip = frame_data[
                    (frame_data["type"] == hand) & (frame_data["landmark_index"] == 20)
                ][["x", "y"]].values

                # Check if all required landmarks are present
                if (
                    wrist.size > 0
                    and thumb_tip.size > 0
                    and index_tip.size > 0
                    and pinky_tip.size > 0
                ):
                    wrist = wrist[0]
                    thumb_tip = thumb_tip[0]
                    index_tip = index_tip[0]
                    pinky_tip = pinky_tip[0]

                    # Calculate features
                    thumb_index_distance = self._calculate_distance(
                        thumb_tip, index_tip
                    )
                    palm_orientation = self._calculate_palm_orientation(
                        wrist, thumb_tip, pinky_tip
                    )

                    # Store results
                    df.loc[
                        (df["frame"] == frame_number) & (df["type"] == hand),
                        f"{hand}_thumb_index_distance",
                    ] = thumb_index_distance
                    df.loc[
                        (df["frame"] == frame_number) & (df["type"] == hand),
                        f"{hand}_palm_orientation",
                    ] = palm_orientation

        return df

    def _calculate_distance(self, point1, point2):
        """
        Calculates the Euclidean distance between two points.

        :param point1: The first point.
        :param point2: The second point.
        :return: The Euclidean distance between the two points.
        """
        return np.sqrt((point1[0] - point2[0]) ** 2 + (point1[1] - point2[1]) ** 2)

    def _calculate_angle(self, point1, point2, point3):
        """
        Calculates the angle between three points.

        :param point1: The first point.
        :param point2: The second point (vertex of the angle).
        :param point3: The third point.
        :return: The angle in degrees.
        """
        vector1 = [point1[0] - point2[0], point1[1] - point2[1]]
        vector2 = [point3[0] - point2[0], point3[1] - point2[1]]
        dot_product = vector1[0] * vector2[0] + vector1[1] * vector2[1]
        magnitude1 = np.sqrt(vector1[0] ** 2 + vector1[1] ** 2)
        magnitude2 = np.sqrt(vector2[0] ** 2 + vector2[1] ** 2)
        angle = np.arccos(dot_product / (magnitude1 * magnitude2))
        return np.degrees(angle)

    def _calculate_palm_orientation(self, wrist, thumb_tip, pinky_tip):
        """
        Calculates the orientation of the palm based on wrist, thumb tip, and pinky tip positions.

        :param wrist: The position of the wrist.
        :param thumb_tip: The position of the thumb tip.
        :param pinky_tip: The position of the pinky tip.
        :return: The orientation of the palm in degrees.
        """
        mid_point = [
            (thumb_tip[0] + pinky_tip[0]) / 2,
            (thumb_tip[1] + pinky_tip[1]) / 2,
        ]
        angle = np.arctan2(mid_point[1] - wrist[1], mid_point[0] - wrist[0])
        return np.degrees(angle)

    def _calculate_finger_joint_angles(self, df):
        for hand in ["right_hand", "left_hand"]:
            for finger, joints in {
                "thumb": [1, 2, 3, 4],
                "index": [5, 6, 7, 8],
                "middle": [9, 10, 11, 12],
                "ring": [13, 14, 15, 16],
                "pinky": [17, 18, 19, 20],
            }.items():
                for i in range(3):
                    base = joints[i]
                    middle = joints[i + 1]
                    tip = joints[i + 2] if i < 2 else None

                    angle_name = f"{hand}_{finger}_{i}_angle"
                    df[angle_name] = np.nan

                    if tip is not None:
                        # Calculate angle between base, middle, and tip
                        df[angle_name] = df.apply(
                            lambda row: self._calculate_angle(
                                row.get(f"{hand}-{base}"),
                                row.get(f"{hand}-{middle}"),
                                row.get(f"{hand}-{tip}"),
                            )
                            if row.get(f"{hand}-{base}") is not None
                            and row.get(f"{hand}-{middle}") is not None
                            and row.get(f"{hand}-{tip}") is not None
                            else np.nan,
                            axis=1,
                        )
                    else:
                        # Calculate orientation angle
                        df[angle_name] = df.apply(
                            lambda row: self._calculate_orientation_angle(
                                row.get(f"{hand}-{base}"), row.get(f"{hand}-{middle}")
                            )
                            if row.get(f"{hand}-{base}") is not None
                            and row.get(f"{hand}-{middle}") is not None
                            else np.nan,
                            axis=1,
                        )
        return df

    def _calculate_finger_orientation_angles(self, df):
        for hand in ["right_hand", "left_hand"]:
            for finger, landmarks in {
                "thumb": [0, 4],
                "index": [0, 8],
                "middle": [0, 12],
                "ring": [0, 16],
                "pinky": [0, 20],
            }.items():
                base = landmarks[0]
                tip = landmarks[1]

                angle_name = f"{hand}_{finger}_orientation_angle"
                df[angle_name] = np.nan

                for frame in df["frame"].unique():
                    frame_data = df[(df["frame"] == frame) & (df["type"] == hand)]

                    base_landmark = frame_data[frame_data["landmark_index"] == base][
                        ["x", "y"]
                    ].values
                    tip_landmark = frame_data[frame_data["landmark_index"] == tip][
                        ["x", "y"]
                    ].values

                    if base_landmark.size > 0 and tip_landmark.size > 0:
                        base_landmark = base_landmark[0]
                        tip_landmark = tip_landmark[0]
                        angle = self._calculate_orientation_angle(
                            base_landmark, tip_landmark
                        )
                        df.loc[
                            (df["frame"] == frame) & (df["type"] == hand), angle_name
                        ] = angle

        return df

    def _calculate_orientation_angle(self, point1, point2):
        """
        Calculate the orientation angle of a line defined by two points relative to the horizontal line.

        :param point1: Coordinates of the first point (x1, y1)
        :param point2: Coordinates of the second point (x2, y2)
        :return: Orientation angle in degrees
        """
        dy = point2[1] - point1[1]
        dx = point2[0] - point1[0]
        angle = np.arctan2(dy, dx)
        return np.degrees(angle)

    def _format_example(self, df, sign):
        """
        Formats a single example into the required output format.

        :param df: The dataframe representing a single example.
        :param sign: The sign label for the example.
        :return: A dictionary representing the formatted example.
        """
        frames = []
        for frame_number, frame_data in df.groupby("frame"):
            frame_info = {
                "frame": int(frame_number),
                "landmarks": [],
                "landmark_types": [],
                "hand_features": {},
            }

            for landmark_type, landmark_data in frame_data.groupby("type"):
                landmarks = landmark_data[["x", "y"]].values.tolist()
                landmark_type = landmark_data["type"].iloc[0]

                frame_info["landmarks"].extend(landmarks)
                frame_info["landmark_types"].extend(
                    [
                        f"{landmark_type}-{int(idx)}"
                        for idx in landmark_data["landmark_index"]
                    ]
                )

            # Add hand features
            for hand in ["right_hand", "left_hand"]:
                thumb_index_distance = frame_data.loc[
                    frame_data["type"] == hand, f"{hand}_thumb_index_distance"
                ].values
                palm_orientation = frame_data.loc[
                    frame_data["type"] == hand, f"{hand}_palm_orientation"
                ].values

                if thumb_index_distance.size > 0 and not pd.isnull(
                    thumb_index_distance[0]
                ):
                    frame_info["hand_features"][
                        f"{hand}_thumb_index_distance"
                    ] = thumb_index_distance[0]
                if palm_orientation.size > 0 and not pd.isnull(palm_orientation[0]):
                    frame_info["hand_features"][
                        f"{hand}_palm_orientation"
                    ] = palm_orientation[0]

                # Add finger orientation angles
                for finger in ["thumb", "index", "middle", "ring", "pinky"]:
                    angle_name = f"{hand}_{finger}_orientation_angle"
                    angle_value = frame_data.loc[
                        frame_data["type"] == hand, angle_name
                    ].values
                    if angle_value.size > 0 and not pd.isnull(angle_value[0]):
                        frame_info["hand_features"][angle_name] = angle_value[0]

            # Remove the "hand_features" key if it's empty
            if not frame_info["hand_features"]:
                frame_info.pop("hand_features")

            frames.append(frame_info)

        result = {"frames": frames, "sign": sign}
        return result

    def process(self):
        """
        Processes all signs and saves the cleaned and formatted data to disk.
        """
        all_signs_data = {}

        for sign in tqdm(self.signs_to_process, desc="Processing signs", unit="sign"):
            all_signs_data[sign] = {"sign": sign, "examples": []}
            parquet_files = self._filter_files_by_sign(sign)
            print(f"Found {len(parquet_files)} parquet files for sign {sign}")

            for parquet_file in tqdm(parquet_files, desc="Cleaning data", unit="file"):
                df = pd.read_parquet(parquet_file)
                df = self._remove_empty_frames(df)
                df["sign"] = sign

                df = self._extract_relevant_landmarks(df)
                df = df.sort_values(by=["frame", "landmark_index"]).reset_index(
                    drop=True
                )
                df = self._handle_nan_values(df)

                if sign in self.label_map:
                    df["label"] = self.label_map[sign]
                else:
                    print(f"Warning: '{sign}' not found in label map. Skipping...")
                    continue

                df = self._drop_z_coordinate(df)
                df = self._normalize_coordinates(df)
                df = self._smooth_landmarks(df, window_length=5, polyorder=3)
                df = self._interpolate_frames(df)
                df = self._calculate_hand_features(df)
                df = self._calculate_finger_joint_angles(df)
                df = self._calculate_finger_orientation_angles(df)
                example = self._format_example(df, sign)

                if example is not None:
                    all_signs_data[sign]["examples"].append(example)
                else:
                    print(
                        f"Warning: No data returned for sign '{sign}' from file '{parquet_file}'."
                    )

            output_filename = os.path.join(
                self.base_dir, f"spatio-temporal/{sign}.json"
            )
            with open(output_filename, "w") as f:
                json.dump(all_signs_data[sign], f, indent=2)

            print(
                f"Data for sign '{sign}' has been cleaned and saved to {output_filename}"
            )


def main():
    """
    Main function to run the ASLGraphDataBuilder.
    """
    load_dotenv()
    BASE_DIR = os.getenv("ASL_SIGNS_BASE_DIRECTORY")
    SIGNS_TO_PROCESS = ["alligator"]
    MAX_FILES_PER_SIGN = 1000
    TARGET_FRAMES = 50
    data_cleaner = ASLGraphDataBuilder(
        BASE_DIR, SIGNS_TO_PROCESS, MAX_FILES_PER_SIGN, TARGET_FRAMES
    )
    data_cleaner.process()


if __name__ == "__main__":
    main()
