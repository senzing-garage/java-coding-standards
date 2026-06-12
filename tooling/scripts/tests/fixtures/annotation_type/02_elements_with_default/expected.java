import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;

@Retention(RetentionPolicy.RUNTIME)
public @interface Configured
{
    String value() default "";
    int priority() default 0;
    Class<?>[] types();
}
