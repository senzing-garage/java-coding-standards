/**
 * Marks a class as scheduled for a future event.
 */
public @interface Scheduled {
    /**
     * The cron-like trigger expression.
     */
    String cron() default "* * * * *";
}
