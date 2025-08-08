# High-Vis Detection AI App

## 🤖 Model

For the high-vis detection task, we recommend using a pre-trained object detection model. These models are efficient and have been trained on large datasets, making them a great starting point.

## 📦 Debian Package Build

To easily distribute and install the application on Debian-based systems, we will package it as a `.deb` file.

### Prerequisites

* The `dpkg-deb` utility

### Steps

    From the directory of this README run the following command:
    ```bash
    dpkg-deb --build high-vis-detection
    ```
    This will create a `high-vis-detection.deb` file in the current directory.

## ☁️ App Installation

Once you have the Debian package, you can upload it to the software repository of your Cumulocity tenant.

### Steps

1.  **Log in to your Cumulocity tenant.**
2.  Navigate to the **Devicemanagement** application.
3.  In the left-hand menu, go to **Management > Software Repository**.
4.  Click **Add software** in the top-right corner.
5.  As software type you should use `apt` and as the version it has to match the version of the debian package (see the file DEBIAN/control)
6.  Drag and drop your `high-vis-detection.deb` file or browse to select it.
7.  Once uploaded, the software will be available in your tenant for deployment to devices.

## 📊 Analytics Installation in Cumulocity

To process the data from your high-heels detection app, you can use Cumulocity's **Analytics Builder**.

### Steps

1.  **Open the Analytics Builder:**
    From the application switcher, open the **Streaming Analytics** application.

2.  **Create a New Model:**
    * Go to the **Analytics Builder** tab and click **New model**.
    * Give your model a name, such as "HighHeelDetectionAnalytics".

3.  **Define the Model Logic:**
    * **Input:** Use an "Event Input" block to receive data from your high-heels detection application. Configure the block to listen for the events sent by your app.
    * **Processing:** Use various blocks to process the input data. For example, you can use a "Threshold" block to trigger an alarm if a high-heel is detected.
    * **Output:** Use an "Alarm" block to create an alarm in Cumulocity when a high-heel is detected. You can also use a "Measurement" block to record detection events as data points.

4.  **Activate the Model:**
    Once you have defined the logic, save and activate the model. It will now process the data from your application in real-time.

## 🖼️ Example Dashboard

You can create a custom dashboard in Cumulocity to visualize the data from your high-heels detection application.

### Example Widgets

* **Alarm List:** This widget can display a list of all alarms generated when high-heels are detected. You can configure it to show critical alarms at the top.
* **Data Point Graph:** This widget can be used to visualize the frequency of high-heel detections over time. This can be useful for identifying trends.
* **Image Widget:** If your application sends images of the detected high-heels, you can use this widget to display them on the dashboard. This provides visual confirmation of the detection events.
* **Map:** If your devices have location data, you can use the map widget to show where high-heel detection events are occurring.

Here is an example of how a dashboard could be laid out:

This dashboard provides a comprehensive overview of the high-heels detection system, allowing you to monitor events and take action when necessary.